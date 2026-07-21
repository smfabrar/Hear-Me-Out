"""FastAPI router for the study platform (mounted on app-api when APP_MODE=study).

Admin endpoints (token-gated) configure the study; participant endpoints run the
resumable, time-limited flow and save artifacts. The system prompt and VC target
never reach the browser: the participant client connects to the VC engine with
only an opaque session_id, and the engine resolves the condition via the internal
GET /api/study/condition/{session_id}.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, Header,
                     HTTPException, UploadFile)
from fastapi.responses import JSONResponse, StreamingResponse

from .analysis import run_session_analysis
from .engine import get_manager
from .models import (EnterRequest, GenerateRequest, ProgressRequest,
                     QuestionnaireRequest, RunStartRequest, SessionStartRequest,
                     StudyConfig, SubmitRequest, default_config)
from .storage import get_backend

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDY_DATA_DIR = Path(os.environ.get("STUDY_DATA_DIR", str(REPO_ROOT / "study_data")))
TARGETS_DIR = STUDY_DATA_DIR / "targets"
SESSIONS_DIR = STUDY_DATA_DIR / "sessions"

ADMIN_TOKEN = os.environ.get("STUDY_ADMIN_TOKEN") or "changeme-study-admin"
if ADMIN_TOKEN == "changeme-study-admin":
    logger.warning("STUDY_ADMIN_TOKEN is not set — using an insecure default. Set it in production.")


def require_admin(x_study_admin_token: str = Header(default="")):
    if x_study_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


def _active_study_or_default(backend) -> dict:
    study = backend.get_active_study()
    if study is None:
        study = backend.upsert_active_study("Pilot Study", default_config())
    return study


def _conditions(study: dict) -> list[dict]:
    return (study.get("config") or {}).get("conditions", [])


def _find_condition(study: dict, idx: int) -> Optional[dict]:
    for c in _conditions(study):
        if c.get("idx") == idx:
            return c
    return None


def _resolve_for_order(backend, study: dict, participant: dict, scenario_order: int):
    """Map a participant's 1-based scenario_order to its condition + target row."""
    order = participant.get("condition_order") or []
    if scenario_order < 1 or scenario_order > len(order):
        raise HTTPException(status_code=400, detail="scenario_order out of range")
    cond = _find_condition(study, order[scenario_order - 1])
    if cond is None:
        raise HTTPException(status_code=400, detail="condition not found for order")
    target = None
    if cond.get("voice_mode") == "vc" and cond.get("target_ref"):
        for t in backend.list_targets(study["id"]):
            if t["ref"] == cond["target_ref"]:
                target = t
                break
    return cond, target


def _scenario_card_for_participant(study: dict, participant: dict, scenario_order: int) -> dict:
    """The participant-facing scenario info only — no prompts or targets."""
    order = participant.get("condition_order") or []
    cond = _find_condition(study, order[scenario_order - 1])
    scenario = (cond or {}).get("scenario", {})
    return {
        "scenario_order": scenario_order,
        "scenario_id": f"scenario_{cond.get('idx')}" if cond else "",
        "role": scenario.get("role", ""),
        "task_goal": scenario.get("task_goal", ""),
        "relevant_facts": scenario.get("relevant_facts", ""),
        "success_criteria": scenario.get("success_criteria", ""),
        "time_limit_s": (cond or {}).get("time_limit_s", 300),
    }


def _run_public(run: Optional[dict]) -> dict:
    if not run:
        return {"status": "not_started"}
    return {
        "status": run["status"],
        "current_step": run.get("current_step") or {},
        "completed": run.get("completed") or {},
        "remaining_seconds": run.get("remaining_seconds", 0),
        "attempt": run.get("attempt", 1),
    }


def build_study_router() -> APIRouter:
    router = APIRouter(prefix="/api/study")
    backend = get_backend()
    manager = get_manager()
    TARGETS_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # =============================== ADMIN ===============================
    @router.get("/config", dependencies=[Depends(require_admin)])
    async def get_config():
        study = _active_study_or_default(backend)
        return {"study_id": study["id"], "name": study["name"], "config": study["config"],
                "targets": backend.list_targets(study["id"]),
                "participants": backend.list_participants(study["id"])}

    @router.put("/config", dependencies=[Depends(require_admin)])
    async def put_config(config: StudyConfig):
        study = backend.upsert_active_study(config.name, config.model_dump())
        return {"study_id": study["id"], "config": study["config"]}

    @router.post("/targets", dependencies=[Depends(require_admin)])
    async def upload_target(wav: UploadFile = File(...), ref: str = Form(...),
                            speaker_id: str = Form(""), label: str = Form("")):
        study = _active_study_or_default(backend)
        TARGETS_DIR.mkdir(parents=True, exist_ok=True)
        dest = TARGETS_DIR / f"study{study['id']}_{ref}.wav"
        with open(dest, "wb") as f:
            shutil.copyfileobj(wav.file, f)
        t = backend.add_target(study["id"], ref, speaker_id or ref, label or wav.filename or ref, str(dest))
        return {"target": t}

    @router.post("/activate", dependencies=[Depends(require_admin)])
    async def activate():
        study = _active_study_or_default(backend)
        backend.set_active(study["id"])
        return {"study_id": study["id"], "active": True}

    @router.post("/stop-engine", dependencies=[Depends(require_admin)])
    async def stop_engine():
        manager.stop_engine()
        return {"engine": "stopped"}

    @router.post("/participants/generate", dependencies=[Depends(require_admin)])
    async def gen_participants(body: GenerateRequest):
        study = _active_study_or_default(backend)
        n_cond = len(_conditions(study))
        order = list(range(1, n_cond + 1)) if n_cond else [1, 2, 3, 4]
        created = backend.generate_participants(study["id"], max(1, body.count), order)
        return {"participants": created}

    @router.get("/runs", dependencies=[Depends(require_admin)])
    async def list_runs():
        study = _active_study_or_default(backend)
        return {"runs": backend.list_runs(study["id"])}

    @router.get("/sessions", dependencies=[Depends(require_admin)])
    async def list_sessions():
        study = _active_study_or_default(backend)
        return {"sessions": backend.list_sessions(study["id"])}

    @router.get("/export", dependencies=[Depends(require_admin)])
    async def export(format: str = "json"):
        study = _active_study_or_default(backend)
        data = {
            "study": {"id": study["id"], "name": study["name"], "config": study["config"]},
            "participants": backend.list_participants(study["id"]),
            "runs": backend.list_runs(study["id"]),
            "sessions": backend.list_sessions(study["id"]),
            "answers": backend.list_answers(study["id"]),
        }
        if format == "json":
            return JSONResponse(data)
        # zip: metadata JSON + all session artifact files
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("study_export.json", json.dumps(data, indent=2))
            if SESSIONS_DIR.exists():
                for p in SESSIONS_DIR.rglob("*"):
                    if p.is_file():
                        z.write(p, str(p.relative_to(STUDY_DATA_DIR)))
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/zip",
                                 headers={"Content-Disposition": "attachment; filename=study_export.zip"})

    # ============================ PARTICIPANT ============================
    def _require_participant(code: str) -> dict:
        p = backend.get_participant_by_code(code)
        if not p:
            raise HTTPException(status_code=404, detail="Invalid code")
        return p

    @router.post("/enter")
    async def enter(body: EnterRequest):
        p = _require_participant(body.code)
        study = backend.get_study(p["study_id"]) or _active_study_or_default(backend)
        order = p.get("condition_order") or []
        scenarios = [_scenario_card_for_participant(study, p, i + 1) for i in range(len(order))]
        run = backend.get_latest_run(p["participant_id"])
        questionnaires = (study.get("config") or {}).get("questionnaires", {})
        return {"participant_id": p["participant_id"], "study_name": study["name"],
                "scenarios": scenarios, "questionnaires": questionnaires,
                "run": _run_public(run)}

    @router.post("/run/start")
    async def run_start(body: RunStartRequest):
        p = _require_participant(body.code)
        study = backend.get_study(p["study_id"]) or _active_study_or_default(backend)
        # Single-live-run guard: block if another participant holds the lock.
        live = backend.get_live_run(study["id"])
        if live and live["participant_id"] != p["participant_id"]:
            raise HTTPException(status_code=409,
                                detail="Another session is in progress, please try again shortly.")
        run = backend.start_run(p["participant_id"], body.mode)
        manager.start_prepare_async(backend, study)
        return {"run": _run_public(run), "prepare": manager.get_state()}

    @router.get("/run/prepare/status")
    async def prepare_status():
        return manager.get_state()

    @router.get("/run/prepare/stream")
    async def prepare_stream():
        async def gen():
            last = -1
            while True:
                state = manager.get_state()
                if state["version"] != last:
                    last = state["version"]
                    yield f"data: {json.dumps(state)}\n\n"
                if state["status"] in ("ready", "error"):
                    break
                await asyncio.sleep(0.4)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/run/progress")
    async def run_progress(body: ProgressRequest):
        p = _require_participant(body.code)
        run = backend.get_latest_run(p["participant_id"])
        if not run:
            raise HTTPException(status_code=400, detail="No active run")
        backend.update_run_progress(run["id"], body.current_step, body.completed)
        return {"ok": True}

    @router.post("/run/submit")
    async def run_submit(body: SubmitRequest):
        p = _require_participant(body.code)
        run = backend.get_latest_run(p["participant_id"])
        if not run:
            raise HTTPException(status_code=400, detail="No active run")
        backend.submit_run(run["id"])
        return {"ok": True, "status": "submitted"}

    def _guard_window(participant_id: str):
        run = backend.get_latest_run(participant_id)
        if not run or run["status"] == "expired":
            raise HTTPException(status_code=440, detail="Session expired")
        if run["status"] == "submitted":
            raise HTTPException(status_code=409, detail="Run already submitted")
        return run

    @router.post("/session/start")
    async def session_start(body: SessionStartRequest):
        p = _require_participant(body.code)
        _guard_window(p["participant_id"])
        study = backend.get_study(p["study_id"]) or _active_study_or_default(backend)
        cond, target = _resolve_for_order(backend, study, p, body.scenario_order)
        session_id = f"{p['participant_id']}_S{body.scenario_order:02d}"
        voice_condition = cond.get("voice_mode", "")
        target_speaker = (target or {}).get("speaker_id", "") if cond.get("voice_mode") == "vc" else ""
        backend.create_session(session_id, p["participant_id"], f"scenario_{cond['idx']}",
                               body.scenario_order, voice_condition, target_speaker)
        return {"session_id": session_id,
                "scenario": _scenario_card_for_participant(study, p, body.scenario_order)}

    @router.get("/condition/{session_id}")
    async def get_condition(session_id: str):
        """Internal: called by the active VC engine over localhost to resolve the
        hidden prompt/target. Not for the browser."""
        session = backend.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Unknown session")
        study = backend.get_study(session["study_id"])
        participants = {pp["participant_id"]: pp for pp in backend.list_participants(session["study_id"])}
        p = participants.get(session["participant_id"])
        if not p or not study:
            raise HTTPException(status_code=404, detail="Unknown participant/study")
        cond, target = _resolve_for_order(backend, study, p, session["scenario_order"])
        default_voice = (study.get("config") or {}).get("default_voice_prompt", "NATF2.pt")
        return {
            "voice_mode": cond.get("voice_mode", "vc"),
            "text_prompt": cond.get("system_prompt", ""),
            "voice_prompt": cond.get("voice_prompt") or default_voice,
            "engine_target_id": (target or {}).get("engine_target_id") if cond.get("voice_mode") == "vc" else None,
            "steps": cond.get("steps", 8),
        }

    @router.post("/session/{session_id}/save")
    async def session_save(session_id: str,
                           background_tasks: BackgroundTasks,
                           participant: UploadFile | None = File(None),
                           participant_raw: UploadFile | None = File(None),
                           model: UploadFile | None = File(None),
                           merged: UploadFile | None = File(None),
                           model_transcript: str = Form("null")):
        """Saves the audio + metadata immediately and returns fast. Transcription
        and VC-quality metrics run in the background so the participant advances
        without waiting (they can be minutes on the first run)."""
        session = backend.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Unknown session")
        out_dir = SESSIONS_DIR / session["participant_id"] / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        files = {}
        for name, up in (("participant", participant), ("participant_raw", participant_raw),
                         ("model", model), ("merged", merged)):
            if up is not None:
                dest = out_dir / f"{name}.wav"
                with open(dest, "wb") as f:
                    shutil.copyfileobj(up.file, f)
                files[name] = str(dest.relative_to(STUDY_DATA_DIR))

        model_turns = json.loads(model_transcript) if model_transcript and model_transcript != "null" else []
        metadata = {
            "participant_id": session["participant_id"], "session_id": session_id,
            "scenario_id": session["scenario_id"], "scenario_order": session["scenario_order"],
            "voice_condition": session["voice_condition"], "target_speaker_id": session["target_speaker_id"],
            "files": files,
        }
        (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        # Persist audio + the model turns immediately; analysis fills in the rest.
        backend.save_session(session_id, files, {"model": model_turns, "participant": None}, None, False)

        converted_path = str(out_dir / "participant.wav") if participant is not None else None
        raw_path = str(out_dir / "participant_raw.wav") if participant_raw is not None else None
        background_tasks.add_task(run_session_analysis, session_id, converted_path, raw_path, model_turns)
        return {"ok": True, "files": files, "analysis": "scheduled"}

    @router.post("/session/{session_id}/end")
    async def session_end(session_id: str, body: dict):
        reason = body.get("reason", "goal_reached")
        if not backend.get_session(session_id):
            raise HTTPException(status_code=404, detail="Unknown session")
        backend.end_session(session_id, reason)
        return {"ok": True}

    @router.post("/session/{session_id}/questionnaire")
    async def session_questionnaire(session_id: str, body: QuestionnaireRequest):
        p = _require_participant(body.code)
        backend.save_answer(p["participant_id"], session_id if session_id != "none" else None,
                            body.kind, body.payload)
        return {"ok": True}

    return router
