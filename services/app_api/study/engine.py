"""VC-engine lifecycle manager for the study platform.

In study mode the VC engine (MeanVC or X-VC — same route surface) is NOT started
at boot. It is brought up the first time a participant starts a run, via
`ensure_ready`, which is idempotent and self-healing: start the engine if down,
wait until it is reachable, (re)load the study's target voices capturing the
engine-returned id per target, and verify PersonaPlex is up. Progress is exposed
as a step list for the participant's "preparing your session…" screen.

Engine start/stop is delegated to infra/vc_engine.sh so the launch logic has a
single source of truth shared with run_all.sh.
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REPO_ROOT = Path(__file__).resolve().parents[3]
VC_ENGINE_SCRIPT = REPO_ROOT / "infra" / "vc_engine.sh"

VC_HOST = os.environ.get("STUDY_VC_HOST", "127.0.0.1")
VC_PORT = int(os.environ.get("MEANVC_PORT", "5002"))
PPLX_PORT = int(os.environ.get("PERSONAPLEX_PROXY_PORT", os.environ.get("PERSONAPLEX_PORT", "8000")))

ENGINE_START_TIMEOUT = int(os.environ.get("STUDY_ENGINE_START_TIMEOUT", "300"))


@dataclass
class PrepareState:
    status: str = "idle"          # idle | preparing | ready | error
    steps: list[dict] = field(default_factory=list)  # [{label, state: running|done|error}]
    error: Optional[str] = None
    version: int = 0              # bumped on every change so SSE clients can diff

    def to_dict(self) -> dict:
        return {"status": self.status, "steps": self.steps, "error": self.error, "version": self.version}


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class VCEngineManager:
    def __init__(self):
        self._lock = threading.Lock()          # serializes prepare runs
        self._state = PrepareState()
        self._state_lock = threading.Lock()
        self._loaded = False                   # targets loaded for the current engine instance
        self._thread: Optional[threading.Thread] = None

    # --- progress state ---
    def get_state(self) -> dict:
        with self._state_lock:
            return self._state.to_dict()

    def _set_status(self, status: str, error: Optional[str] = None):
        with self._state_lock:
            self._state.status = status
            self._state.error = error
            self._state.version += 1

    def _reset_steps(self):
        with self._state_lock:
            self._state.steps = []
            self._state.error = None
            self._state.status = "preparing"
            self._state.version += 1

    def _step(self, label: str) -> int:
        with self._state_lock:
            self._state.steps.append({"label": label, "state": "running"})
            self._state.version += 1
            return len(self._state.steps) - 1

    def _finish_step(self, idx: int, state: str = "done"):
        with self._state_lock:
            if 0 <= idx < len(self._state.steps):
                self._state.steps[idx]["state"] = state
                self._state.version += 1

    # --- engine control ---
    def is_engine_up(self) -> bool:
        return _port_open(VC_HOST, VC_PORT)

    def _run_script(self, action: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(VC_ENGINE_SCRIPT), action],
                              capture_output=True, text=True, cwd=str(REPO_ROOT))

    def stop_engine(self) -> None:
        if VC_ENGINE_SCRIPT.exists():
            self._run_script("stop")
        self._loaded = False
        self._set_status("idle")

    def _start_engine_and_wait(self):
        if not self.is_engine_up():
            if not VC_ENGINE_SCRIPT.exists():
                raise RuntimeError(f"VC engine launcher missing: {VC_ENGINE_SCRIPT}")
            self._run_script("start")
            self._loaded = False
            deadline = time.time() + ENGINE_START_TIMEOUT
            while time.time() < deadline:
                if self.is_engine_up():
                    return
                time.sleep(2)
            raise RuntimeError("VC engine did not become reachable in time")

    def _load_targets(self, backend, study_id: int):
        targets = backend.list_targets(study_id)
        for i, t in enumerate(targets):
            wav_path = t["wav_path"]
            if not os.path.exists(wav_path):
                raise RuntimeError(f"Target WAV missing: {wav_path}")
            with open(wav_path, "rb") as f:
                resp = requests.post(
                    f"https://{VC_HOST}:{VC_PORT}/api/meanvc/load-target",
                    files={"wav": (os.path.basename(wav_path), f, "audio/wav")},
                    verify=False, timeout=120)
            resp.raise_for_status()
            engine_target_id = resp.json().get("target_id")
            if not engine_target_id:
                raise RuntimeError(f"load-target returned no target_id for {t['ref']}")
            backend.set_engine_target_id(t["id"], engine_target_id)

    # --- the idempotent core ---
    def ensure_ready(self, backend, study: dict) -> None:
        """Blocking. Bring the engine up and load targets if needed. Safe to call
        repeatedly; skips fast when already prepared."""
        with self._lock:
            study_id = study["id"]
            targets = backend.list_targets(study_id)
            already = self.is_engine_up() and self._loaded and all(t.get("engine_target_id") for t in targets)
            if already:
                self._set_status("ready")
                return

            self._reset_steps()
            try:
                s = self._step("Starting voice engine")
                self._start_engine_and_wait()
                self._finish_step(s)

                s = self._step(f"Loading {len(targets)} target voice(s)")
                self._load_targets(backend, study_id)
                self._loaded = True
                self._finish_step(s)

                s = self._step("Checking speech model")
                if not _port_open(VC_HOST, PPLX_PORT):
                    self._finish_step(s, "error")
                    raise RuntimeError(f"PersonaPlex not reachable on port {PPLX_PORT}")
                self._finish_step(s)

                self._set_status("ready")
            except Exception as e:  # noqa: BLE001 - surface any prepare failure to the UI
                self._set_status("error", str(e))
                raise

    def start_prepare_async(self, backend, study: dict) -> None:
        """Kick off ensure_ready in the background so the endpoint can return and
        the client can stream progress. No-op if a prepare is already running."""
        if self._thread and self._thread.is_alive():
            return
        self._set_status("preparing")

        def _run():
            try:
                self.ensure_ready(backend, study)
            except Exception:  # noqa: BLE001 - state already carries the error
                pass

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()


_manager: Optional[VCEngineManager] = None


def get_manager() -> VCEngineManager:
    global _manager
    if _manager is None:
        _manager = VCEngineManager()
    return _manager
