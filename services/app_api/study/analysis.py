"""Background per-session analysis so participants never wait for it.

After a scenario's audio is uploaded, this runs Whisper transcription + the
VC-quality metrics (via metrics.analyze_voices, which transcribes both clips)
off the participant's critical path and writes the results back to the session.
The participant has already advanced to the questionnaire by then.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# metrics.py lives one level up (services/app_api/); make it importable.
_APP_API_DIR = str(Path(__file__).resolve().parents[1])
if _APP_API_DIR not in sys.path:
    sys.path.insert(0, _APP_API_DIR)


def run_session_analysis(session_id: str, converted_wav: str | None,
                         raw_wav: str | None, model_transcript: list | None) -> None:
    from .storage import get_backend

    backend = get_backend()
    transcript = {"model": model_transcript or [], "participant": None}
    metrics = None
    audiobox = False

    try:
        # Prefer comparing raw (original) vs converted; for a natural condition
        # there's no separate raw clip, so analyze the converted clip against
        # itself (metrics are trivial but the transcript is still extracted).
        clip_b = converted_wav if converted_wav and os.path.exists(converted_wav) else None
        clip_a = raw_wav if raw_wav and os.path.exists(raw_wav) else clip_b
        if clip_a and clip_b:
            from metrics import analyze_voices

            metrics = analyze_voices(clip_a, clip_b)
            transcript["participant"] = (metrics.get("response_b") or {}).get("transcript")
            audiobox = bool(metrics.get("audiobox_available"))
    except Exception as e:  # noqa: BLE001 - analysis is best-effort; audio is already saved
        logger.warning(f"[study] analysis failed for {session_id}: {e}")

    try:
        backend.update_session_analysis(session_id, transcript, metrics, audiobox)
        # Mirror JSON next to the WAVs so the ZIP export is self-contained.
        base = converted_wav or raw_wav
        if base:
            out_dir = Path(base).parent
            (out_dir / "transcript.json").write_text(json.dumps(transcript, indent=2))
            (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
        logger.info(f"[study] analysis complete for {session_id} (audiobox={audiobox})")
    except Exception as e:  # noqa: BLE001
        logger.error(f"[study] could not persist analysis for {session_id}: {e}")
