"""Background jobs with persisted, stage-based progress and cooperative cancellation.

Progress values come from the work itself (files analysed, frames scanned, segments rendered,
transcription position), never from timers. Cancelling kills the running FFmpeg/analysis process.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from video_editor import ffmpeg_ops

from .. import db

STAGES: dict[str, list[tuple[str, str, float]]] = {
    "generate": [("analyze", "Analyzing media", 0.20), ("scenes", "Detecting scenes", 0.12),
                 ("highlights", "Selecting highlights", 0.03), ("decisions", "Generating edit decisions", 0.05),
                 ("audio_captions", "Processing audio and captions", 0.15), ("render", "Rendering video", 0.40),
                 ("finalize", "Finalizing output", 0.05)],
    "textvideo": [("plan", "Planning scenes", 0.03), ("scenes", "Generating scenes with AI", 0.72),
                  ("assemble", "Assembling the timeline", 0.05), ("render", "Rendering video", 0.17),
                  ("finalize", "Finalizing output", 0.03)],
    "render": [("render", "Rendering video", 0.95), ("finalize", "Finalizing output", 0.05)],
    "export": [("render", "Rendering video", 0.95), ("finalize", "Finalizing output", 0.05)],
    "transcribe": [("audio_captions", "Transcribing speech", 1.0)],
    "matte": [("matte", "Finding the subject", 1.0)],
    "ingest": [("process", "Processing media", 1.0)],
}

_pools = {"ingest": ThreadPoolExecutor(2, thread_name_prefix="ff-ingest"),
          "work": ThreadPoolExecutor(1, thread_name_prefix="ff-work")}
_cancel: dict[str, threading.Event] = {}
_handlers: dict[str, Callable] = {}


class JobFailed(RuntimeError):
    """Raise for expected failures: the message is shown to the user as-is."""


def handler(kind: str):
    def deco(fn):
        _handlers[kind] = fn
        return fn
    return deco


class JobContext:
    def __init__(self, job_id: str, kind: str, project_id: str):
        self.id, self.kind, self.project_id = job_id, kind, project_id
        self.stages = STAGES[kind]
        self._base = 0.0
        self._weight = 0.0
        self._stage = None
        self._last_write = 0.0

    def stage(self, key: str, message: str | None = None) -> None:
        self.check()
        base = 0.0
        for k, label, w in self.stages:
            if k == key:
                self._base, self._weight, self._stage = base, w, key
                self._write(base, message or label, force=True)
                return
            base += w
        raise KeyError(key)

    def update(self, frac: float, message: str | None = None) -> None:
        self.check()
        self._write(self._base + self._weight * max(0.0, min(1.0, frac)), message)

    def check(self) -> None:
        ev = _cancel.get(self.id)
        if ev is not None and ev.is_set():
            raise ffmpeg_ops.Cancelled("Cancelled by user")

    def _write(self, progress: float, message: str | None, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_write < 0.2:
            return
        self._last_write = now
        if message is None:
            db.execute("UPDATE jobs SET stage=?, progress=?, updated_at=? WHERE id=?",
                       (self._stage, round(progress, 4), now, self.id))
        else:
            db.execute("UPDATE jobs SET stage=?, progress=?, message=?, updated_at=? WHERE id=?",
                       (self._stage, round(progress, 4), message, now, self.id))


def to_dict(row: dict) -> dict:
    return {"id": row["id"], "projectId": row["project_id"], "kind": row["kind"], "status": row["status"],
            "stage": row["stage"], "progress": row["progress"], "message": row["message"], "error": row["error"],
            "params": {k: v for k, v in db.loads(row["params"], {}).items() if k != "doc"},
            "result": db.loads(row["result"]), "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            "stages": [{"key": k, "label": label} for k, label, _ in STAGES.get(row["kind"], [])]}


def get(job_id: str) -> dict | None:
    row = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    return to_dict(row) if row else None


def params_of(job_id: str) -> dict:
    row = db.one("SELECT params FROM jobs WHERE id=?", (job_id,))
    return db.loads(row["params"], {}) if row else {}


def list_for(project_id: str, limit: int = 20) -> list[dict]:
    rows = db.query("SELECT * FROM jobs WHERE project_id=? AND kind != 'ingest' ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit))
    return [to_dict(r) for r in rows]


def active(project_id: str, kind: str) -> dict | None:
    row = db.one("SELECT * FROM jobs WHERE project_id=? AND kind=? AND status IN ('queued','running') "
                 "ORDER BY created_at DESC LIMIT 1", (project_id, kind))
    return to_dict(row) if row else None


def submit(kind: str, project_id: str, params: dict) -> dict:
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    db.execute("INSERT INTO jobs (id, project_id, kind, status, stage, progress, message, params, created_at, "
               "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (job_id, project_id, kind, "queued", None, 0.0, "Waiting to start…", db.dumps(params), now, now))
    _cancel[job_id] = threading.Event()
    pool = _pools["ingest" if kind in ("ingest", "textvideo") else "work"]
    pool.submit(_run, job_id, kind, project_id, params)
    return get(job_id)


def _finish(job_id: str, status: str, error: str | None = None, result: dict | None = None,
            message: str | None = None) -> None:
    db.execute("UPDATE jobs SET status=?, error=?, result=?, message=COALESCE(?, message), progress=CASE WHEN ?='done' "
               "THEN 1 ELSE progress END, updated_at=? WHERE id=?",
               (status, error, db.dumps(result) if result is not None else None, message, status, time.time(), job_id))


def _friendly(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    lines = [l for l in text.splitlines() if l.strip()]
    if isinstance(exc, ffmpeg_ops.FFmpegError) and len(lines) > 1:
        # first line says what failed; the last stderr line usually says why
        return f"{lines[0]} {lines[-1].strip()}"[:600]
    return text[:600]


def _run(job_id: str, kind: str, project_id: str, params: dict) -> None:
    ev = _cancel.get(job_id)
    if ev is not None and ev.is_set():
        _finish(job_id, "cancelled", message="Cancelled")
        return
    db.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=?", (time.time(), job_id))
    ctx = JobContext(job_id, kind, project_id)
    ffmpeg_ops.set_cancel_event(ev)
    try:
        result = _handlers[kind](ctx, project_id, params)
        _finish(job_id, "done", result=result or {}, message="Done")
    except ffmpeg_ops.Cancelled:
        _finish(job_id, "cancelled", message="Cancelled")
    except Exception as exc:  # report every failure to the UI instead of dying silently
        if not isinstance(exc, JobFailed):
            traceback.print_exc()
        _finish(job_id, "failed", error=_friendly(exc), message="Failed")
        on_fail = _handlers.get(f"{kind}:failed")
        if on_fail:
            on_fail(project_id, params, _friendly(exc))
    finally:
        ffmpeg_ops.set_cancel_event(None)
        _cancel.pop(job_id, None)


def cancel(job_id: str) -> dict | None:
    job = get(job_id)
    if job and job["status"] in ("queued", "running"):
        ev = _cancel.get(job_id)
        if ev is not None:
            ev.set()
        else:  # not tracked by this process (e.g. stale row): close it out
            _finish(job_id, "cancelled", message="Cancelled")
    return get(job_id)


def retry(job_id: str) -> dict:
    row = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if row is None:
        raise KeyError(job_id)
    return submit(row["kind"], row["project_id"], db.loads(row["params"], {}))


def fail_interrupted() -> None:
    db.execute("UPDATE jobs SET status='failed', error='Interrupted by a server restart. Retry to run it again.', "
               "message='Interrupted', updated_at=? WHERE status IN ('queued','running')", (time.time(),))
