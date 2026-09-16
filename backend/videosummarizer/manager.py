from __future__ import annotations

import queue
import shutil
import threading
from pathlib import Path

from .database import ACTIVE_STATUSES, Database
from .pipeline import JobCancelled, Pipeline, PipelineError


class JobManager:
    def __init__(self, database: Database, pipeline: Pipeline):
        self.database = database
        self.pipeline = pipeline
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self._active_lock = threading.Lock()
        self.active_job_id: str | None = None
        self._thread = threading.Thread(target=self._worker, name="video-summary-worker", daemon=True)

    def start(self) -> None:
        self.database.mark_interrupted()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.active_job_id:
            self.cancel(self.active_job_id)
        self._queue.put(None)
        self._thread.join(timeout=5)

    def enqueue(self, job_id: str) -> None:
        self._queue.put(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.database.get_job(job_id)
        if not job or job["status"] not in ACTIVE_STATUSES:
            return False
        self.database.update_job(job_id, cancel_requested=1, stage_message="正在安全取消任务")
        return True

    def retry(self, job_id: str) -> dict | None:
        job = self.database.get_job(job_id)
        if not job or job["status"] not in {"failed", "canceled"}:
            return None
        job_dir = Path(job["job_dir"])
        job_dir.mkdir(parents=True, exist_ok=True)
        reset = self.database.reset_for_retry(job_id)
        if reset:
            self.enqueue(job_id)
        return reset

    def delete(self, job_id: str) -> bool:
        job = self.database.get_job(job_id)
        if not job or job["status"] in ACTIVE_STATUSES:
            return False
        job_dir = Path(job["job_dir"]).resolve()
        if job_dir.exists():
            shutil.rmtree(job_dir)
        return self.database.delete_job(job_id)

    def _worker(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if job_id is None:
                return
            with self._active_lock:
                self.active_job_id = job_id
            try:
                self.pipeline.run(job_id)
            except JobCancelled:
                pass
            except PipelineError as exc:
                self.database.update_job(job_id, status="failed", stage_message="处理失败", error_code=exc.code, error_message=exc.message)
            except Exception as exc:
                self.database.update_job(job_id, status="failed", stage_message="处理失败", error_code="INTERNAL_ERROR", error_message=str(exc))
            finally:
                with self._active_lock:
                    self.active_job_id = None
                self._queue.task_done()
