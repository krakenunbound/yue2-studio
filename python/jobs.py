from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from queue import Queue
from typing import Any, Callable
import model_manager

log = logging.getLogger("yue2.jobs")
JobFn = Callable[["Job"], dict[str, Any]]


@dataclass
class Job:
    id: str
    kind: str
    params: dict[str, Any]
    status: str = "queued"
    phase: str = "Queued"
    progress: float = 0.0
    eta_seconds: float | None = None
    stage_progress: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    client: Any = None
    subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = field(default_factory=list)

    def emit(self) -> None:
        snapshot = {"type": "snapshot", **self.snapshot()}
        for loop, queue in list(self.subscribers):
            try: loop.call_soon_threadsafe(queue.put_nowait, snapshot)
            except Exception: pass

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "status": self.status,
            "phase": self.phase, "progress": self.progress, "result": self.result,
            "eta_seconds": self.eta_seconds,
            "stage_progress": self.stage_progress,
            "error": self.error, "created_at": self.created_at,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.queue: Queue[tuple[Job, JobFn]] = Queue()
        self.lock = threading.RLock()
        threading.Thread(target=self._loop, name="yue2-jobs", daemon=True).start()

    def submit(self, kind: str, params: dict[str, Any], fn: JobFn) -> Job:
        with model_manager.activity_lock:
            if model_manager.busy():
                raise model_manager.InstallationBusyError("Wait for the model installation to finish before starting a job.")
            job = Job(uuid.uuid4().hex, kind, params)
            with self.lock: self.jobs[job.id] = job
            self.queue.put((job, fn))
        queued = {
            "yue2": "Queued YuE2 job %s",
            "stable_sfx": "Queued sound effect job %s",
            "cover_art": "Queued cover art job %s",
            "stems": "Queued stem extraction job %s",
            "audio_export": "Queued audio export job %s",
            "lyrics_sync": "Queued lyric sync job %s",
            "sheetsage": "Queued SheetSage2 transcription job %s",
        }.get(kind, "Queued job %s")
        log.info(queued, job.id[:8])
        return job

    def get(self, job_id: str) -> Job | None:
        with self.lock: return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        with self.lock: return sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)

    def cancel_job(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in {"succeeded", "failed", "cancelled"}: return False
        job.cancel.set()
        if job.status == "queued":
            job.status, job.phase, job.finished_at = "cancelled", "Cancelled", time.time()
            job.emit()
        return True

    def subscribe(self, job_id: str):
        job = self.get(job_id)
        if not job: return None
        loop, queue = asyncio.get_event_loop(), asyncio.Queue(maxsize=128)
        entry = (loop, queue)
        job.subscribers.append(entry)
        queue.put_nowait({"type": "snapshot", **job.snapshot()})
        return queue, lambda: job.subscribers.remove(entry) if entry in job.subscribers else None

    def _loop(self) -> None:
        while True:
            job, fn = self.queue.get()
            if job.cancel.is_set():
                self.queue.task_done(); continue
            opening = {
                "yue2": "Submitting to YuE2", "cover_art": "Starting cover art",
                "stems": "Starting stem extraction", "audio_export": "Preparing audio export",
                "lyrics_sync": "Starting lyric synchronization",
                "stable_sfx": "Preparing sound generator",
            }.get(job.kind, "Starting job")
            job.status, job.phase, job.progress = "running", opening, 0.05
            job.started_at = time.time(); job.emit()
            try:
                job.result = fn(job)
                if job.cancel.is_set():
                    job.status, job.phase = "cancelled", "Cancelled"
                else:
                    finished = {"yue2": "Song ready", "cover_art": "Cover art ready", "stems": "Stems ready", "audio_export": "Download ready", "lyrics_sync": "Timed lyrics ready", "stable_sfx": "Sound effect ready"}.get(job.kind, "Complete")
                    job.status, job.phase, job.progress = "succeeded", finished, 1.0
            except Exception as error:
                if job.cancel.is_set(): job.status, job.phase = "cancelled", "Cancelled"
                else:
                    job.status, job.phase, job.error = "failed", "Job failed", str(error)
                    log.exception("Studio job %s failed", job.id[:8])
            finally:
                job.client = None; job.finished_at = time.time(); job.emit(); self.queue.task_done()


manager = JobManager()
