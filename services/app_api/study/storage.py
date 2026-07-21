"""Persistence for the study platform.

`StorageBackend` is the interface; `SqliteBackend` is the pilot implementation
(one SQLite file, WAV/JSON artifacts on disk). A future `MongoBackend` can
implement the same interface without touching the router. Rows are returned as
plain dicts (JSON columns already decoded) to keep the interface backend-neutral.
"""

from __future__ import annotations

import abc
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

# A study run must be submitted within this window from (re)start; otherwise it
# expires and the participant may resume (keeping completed scenarios, fresh
# window) or restart.
RUN_WINDOW_SECONDS = 3600


def _now() -> float:
    return time.time()


class StorageBackend(abc.ABC):
    # --- study config ---
    @abc.abstractmethod
    def get_active_study(self) -> Optional[dict]: ...
    @abc.abstractmethod
    def get_study(self, study_id: int) -> Optional[dict]: ...
    @abc.abstractmethod
    def upsert_active_study(self, name: str, config: dict) -> dict: ...
    @abc.abstractmethod
    def set_active(self, study_id: int) -> None: ...

    # --- targets ---
    @abc.abstractmethod
    def add_target(self, study_id: int, ref: str, speaker_id: str, label: str, wav_path: str) -> dict: ...
    @abc.abstractmethod
    def list_targets(self, study_id: int) -> list[dict]: ...
    @abc.abstractmethod
    def set_engine_target_id(self, target_id: int, engine_target_id: Optional[str]) -> None: ...

    # --- participants ---
    @abc.abstractmethod
    def generate_participants(self, study_id: int, count: int, condition_order: list[int]) -> list[dict]: ...
    @abc.abstractmethod
    def get_participant_by_code(self, code: str) -> Optional[dict]: ...
    @abc.abstractmethod
    def list_participants(self, study_id: int) -> list[dict]: ...

    # --- runs ---
    @abc.abstractmethod
    def get_latest_run(self, participant_id: str) -> Optional[dict]: ...
    @abc.abstractmethod
    def start_run(self, participant_id: str, mode: str) -> dict: ...
    @abc.abstractmethod
    def update_run_progress(self, run_id: int, current_step: dict, completed: dict) -> None: ...
    @abc.abstractmethod
    def submit_run(self, run_id: int) -> None: ...
    @abc.abstractmethod
    def get_live_run(self, study_id: int) -> Optional[dict]: ...
    @abc.abstractmethod
    def list_runs(self, study_id: int) -> list[dict]: ...

    # --- sessions (one scenario call) ---
    @abc.abstractmethod
    def create_session(self, session_id: str, participant_id: str, scenario_id: str,
                       scenario_order: int, voice_condition: str, target_speaker_id: str) -> dict: ...
    @abc.abstractmethod
    def save_session(self, session_id: str, files: dict, transcript: Any, metrics: Any,
                     audiobox_available: bool) -> None: ...
    @abc.abstractmethod
    def update_session_analysis(self, session_id: str, transcript: Any, metrics: Any,
                                audiobox_available: bool) -> None: ...
    @abc.abstractmethod
    def end_session(self, session_id: str, end_reason: str) -> None: ...
    @abc.abstractmethod
    def get_session(self, session_id: str) -> Optional[dict]: ...
    @abc.abstractmethod
    def list_sessions(self, study_id: int) -> list[dict]: ...

    # --- questionnaire answers ---
    @abc.abstractmethod
    def save_answer(self, participant_id: str, session_id: Optional[str], kind: str, payload: Any) -> None: ...
    @abc.abstractmethod
    def list_answers(self, study_id: int) -> list[dict]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS study (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 0,
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS target (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  study_id INTEGER NOT NULL,
  ref TEXT NOT NULL,
  speaker_id TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '',
  wav_path TEXT NOT NULL,
  engine_target_id TEXT,
  UNIQUE(study_id, ref)
);
CREATE TABLE IF NOT EXISTS participant (
  participant_id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  study_id INTEGER NOT NULL,
  condition_order_json TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS run (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  participant_id TEXT NOT NULL,
  study_id INTEGER NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'in_progress',
  current_step_json TEXT NOT NULL DEFAULT '{}',
  completed_json TEXT NOT NULL DEFAULT '{}',
  started_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  submitted_at REAL
);
CREATE TABLE IF NOT EXISTS session (
  session_id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  study_id INTEGER NOT NULL,
  scenario_id TEXT NOT NULL,
  scenario_order INTEGER NOT NULL,
  voice_condition TEXT NOT NULL DEFAULT '',
  target_speaker_id TEXT NOT NULL DEFAULT '',
  started_at REAL NOT NULL,
  ended_at REAL,
  end_reason TEXT,
  files_json TEXT,
  transcript_json TEXT,
  metrics_json TEXT,
  audiobox_available INTEGER
);
CREATE TABLE IF NOT EXISTS answer (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  participant_id TEXT NOT NULL,
  study_id INTEGER NOT NULL,
  session_id TEXT,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""


def _loads(row: sqlite3.Row, json_cols: tuple[str, ...]) -> dict:
    d = dict(row)
    for c in json_cols:
        if c in d and d[c] is not None:
            try:
                d[c[:-5] if c.endswith("_json") else c] = json.loads(d[c])
            except (json.JSONDecodeError, TypeError):
                d[c[:-5] if c.endswith("_json") else c] = None
    return d


class SqliteBackend(StorageBackend):
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- study config ---
    def get_active_study(self) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM study WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
        return _loads(row, ("config_json",)) if row else None

    def get_study(self, study_id: int) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM study WHERE id=?", (study_id,)).fetchone()
        return _loads(row, ("config_json",)) if row else None

    def upsert_active_study(self, name: str, config: dict) -> dict:
        """Update the active study's config, or create the first study if none exists."""
        with self._conn() as c:
            row = c.execute("SELECT id FROM study WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                c.execute("UPDATE study SET name=?, config_json=? WHERE id=?",
                          (name, json.dumps(config), row["id"]))
                sid = row["id"]
            else:
                cur = c.execute("INSERT INTO study(name, active, config_json, created_at) VALUES(?,1,?,?)",
                                (name, json.dumps(config), _now()))
                sid = cur.lastrowid
        return self.get_study(sid)

    def set_active(self, study_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE study SET active=0")
            c.execute("UPDATE study SET active=1 WHERE id=?", (study_id,))

    # --- targets ---
    def add_target(self, study_id: int, ref: str, speaker_id: str, label: str, wav_path: str) -> dict:
        with self._conn() as c:
            c.execute(
                "INSERT INTO target(study_id, ref, speaker_id, label, wav_path) VALUES(?,?,?,?,?) "
                "ON CONFLICT(study_id, ref) DO UPDATE SET speaker_id=excluded.speaker_id, "
                "label=excluded.label, wav_path=excluded.wav_path, engine_target_id=NULL",
                (study_id, ref, speaker_id, label, wav_path))
            row = c.execute("SELECT * FROM target WHERE study_id=? AND ref=?", (study_id, ref)).fetchone()
        return dict(row)

    def list_targets(self, study_id: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM target WHERE study_id=? ORDER BY id", (study_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_engine_target_id(self, target_id: int, engine_target_id: Optional[str]) -> None:
        with self._conn() as c:
            c.execute("UPDATE target SET engine_target_id=? WHERE id=?", (engine_target_id, target_id))

    # --- participants ---
    def generate_participants(self, study_id: int, count: int, condition_order: list[int]) -> list[dict]:
        created = []
        with self._conn() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM participant WHERE study_id=?", (study_id,)).fetchone()["n"]
            for i in range(count):
                pid = f"P{n + i + 1:04d}"
                code = _gen_code()
                while c.execute("SELECT 1 FROM participant WHERE code=?", (code,)).fetchone():
                    code = _gen_code()
                c.execute(
                    "INSERT INTO participant(participant_id, code, study_id, condition_order_json, created_at) "
                    "VALUES(?,?,?,?,?)",
                    (pid, code, study_id, json.dumps(condition_order), _now()))
                created.append({"participant_id": pid, "code": code, "condition_order": condition_order})
        return created

    def get_participant_by_code(self, code: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM participant WHERE code=?", (code.strip(),)).fetchone()
        return _loads(row, ("condition_order_json",)) if row else None

    def list_participants(self, study_id: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM participant WHERE study_id=? ORDER BY participant_id", (study_id,)).fetchall()
        return [_loads(r, ("condition_order_json",)) for r in rows]

    # --- runs ---
    def get_latest_run(self, participant_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM run WHERE participant_id=? ORDER BY attempt DESC LIMIT 1",
                            (participant_id,)).fetchone()
        return self._run_dict(row) if row else None

    def start_run(self, participant_id: str, mode: str) -> dict:
        now = _now()
        expires = now + RUN_WINDOW_SECONDS
        with self._conn() as c:
            prow = c.execute("SELECT study_id FROM participant WHERE participant_id=?", (participant_id,)).fetchone()
            study_id = prow["study_id"]
            latest = c.execute("SELECT * FROM run WHERE participant_id=? ORDER BY attempt DESC LIMIT 1",
                               (participant_id,)).fetchone()
            resumable = latest and mode == "resume" and latest["status"] in ("in_progress", "expired")
            if resumable:
                # Keep completed scenarios + current step; fresh window.
                c.execute("UPDATE run SET status='in_progress', started_at=?, expires_at=?, submitted_at=NULL "
                          "WHERE id=?", (now, expires, latest["id"]))
                rid = latest["id"]
            else:
                attempt = (latest["attempt"] + 1) if latest else 1
                cur = c.execute(
                    "INSERT INTO run(participant_id, study_id, attempt, status, current_step_json, "
                    "completed_json, started_at, expires_at) VALUES(?,?,?,?,?,?,?,?)",
                    (participant_id, study_id, attempt, "in_progress", "{}", "{}", now, expires))
                rid = cur.lastrowid
            row = c.execute("SELECT * FROM run WHERE id=?", (rid,)).fetchone()
        return self._run_dict(row)

    def update_run_progress(self, run_id: int, current_step: dict, completed: dict) -> None:
        with self._conn() as c:
            c.execute("UPDATE run SET current_step_json=?, completed_json=? WHERE id=?",
                      (json.dumps(current_step), json.dumps(completed), run_id))

    def submit_run(self, run_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE run SET status='submitted', submitted_at=? WHERE id=?", (_now(), run_id))

    def get_live_run(self, study_id: int) -> Optional[dict]:
        """A run currently holding the single-live-run lock (in_progress, not yet expired)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM run WHERE study_id=? AND status='in_progress' AND expires_at > ? "
                "ORDER BY started_at DESC LIMIT 1", (study_id, _now())).fetchone()
        return self._run_dict(row) if row else None

    def list_runs(self, study_id: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM run WHERE study_id=? ORDER BY started_at DESC", (study_id,)).fetchall()
        return [self._run_dict(r) for r in rows]

    def _run_dict(self, row: sqlite3.Row) -> dict:
        d = _loads(row, ("current_step_json", "completed_json"))
        # Reflect expiry lazily so callers see accurate status without a sweep.
        if d["status"] == "in_progress" and d["expires_at"] is not None and d["expires_at"] < _now():
            d["status"] = "expired"
        d["remaining_seconds"] = max(0, int(d["expires_at"] - _now())) if d.get("expires_at") else 0
        return d

    # --- sessions ---
    def create_session(self, session_id, participant_id, scenario_id, scenario_order,
                        voice_condition, target_speaker_id) -> dict:
        with self._conn() as c:
            prow = c.execute("SELECT study_id FROM participant WHERE participant_id=?", (participant_id,)).fetchone()
            study_id = prow["study_id"]
            c.execute(
                "INSERT OR REPLACE INTO session(session_id, participant_id, study_id, scenario_id, "
                "scenario_order, voice_condition, target_speaker_id, started_at) VALUES(?,?,?,?,?,?,?,?)",
                (session_id, participant_id, study_id, scenario_id, scenario_order,
                 voice_condition, target_speaker_id, _now()))
            row = c.execute("SELECT * FROM session WHERE session_id=?", (session_id,)).fetchone()
        return dict(row)

    def save_session(self, session_id, files, transcript, metrics, audiobox_available) -> None:
        with self._conn() as c:
            c.execute("UPDATE session SET files_json=?, transcript_json=?, metrics_json=?, "
                      "audiobox_available=? WHERE session_id=?",
                      (json.dumps(files), json.dumps(transcript), json.dumps(metrics),
                       1 if audiobox_available else 0, session_id))

    def update_session_analysis(self, session_id, transcript, metrics, audiobox_available) -> None:
        with self._conn() as c:
            c.execute("UPDATE session SET transcript_json=?, metrics_json=?, audiobox_available=? "
                      "WHERE session_id=?",
                      (json.dumps(transcript), json.dumps(metrics),
                       1 if audiobox_available else 0, session_id))

    def end_session(self, session_id, end_reason) -> None:
        with self._conn() as c:
            c.execute("UPDATE session SET ended_at=?, end_reason=? WHERE session_id=?",
                      (_now(), end_reason, session_id))

    def get_session(self, session_id) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM session WHERE session_id=?", (session_id,)).fetchone()
        return _loads(row, ("files_json", "transcript_json", "metrics_json")) if row else None

    def list_sessions(self, study_id) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM session WHERE study_id=? ORDER BY started_at", (study_id,)).fetchall()
        return [_loads(r, ("files_json", "transcript_json", "metrics_json")) for r in rows]

    # --- answers ---
    def save_answer(self, participant_id, session_id, kind, payload) -> None:
        with self._conn() as c:
            prow = c.execute("SELECT study_id FROM participant WHERE participant_id=?", (participant_id,)).fetchone()
            study_id = prow["study_id"] if prow else 0
            c.execute("INSERT INTO answer(participant_id, study_id, session_id, kind, payload_json, created_at) "
                      "VALUES(?,?,?,?,?,?)",
                      (participant_id, study_id, session_id, kind, json.dumps(payload), _now()))

    def list_answers(self, study_id) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM answer WHERE study_id=? ORDER BY created_at", (study_id,)).fetchall()
        return [_loads(r, ("payload_json",)) for r in rows]


def _gen_code() -> str:
    """Human-typable participant code, avoiding ambiguous chars (0/O, 1/I/L)."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


_backend: Optional[StorageBackend] = None


def get_backend() -> StorageBackend:
    """Process-wide backend singleton, selected by env (SQLite for the pilot)."""
    global _backend
    if _backend is None:
        kind = os.environ.get("STUDY_STORAGE", "sqlite").lower()
        if kind == "sqlite":
            repo_root = Path(__file__).resolve().parents[3]
            db_path = os.environ.get("STUDY_DB_PATH", str(repo_root / "study.db"))
            _backend = SqliteBackend(db_path)
        else:
            raise RuntimeError(f"Unknown STUDY_STORAGE backend: {kind}")
    return _backend
