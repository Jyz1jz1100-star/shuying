from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_STATUSES = ("queued", "probing", "downloading", "transcribing", "proofreading", "summarizing", "rendering")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with self.connect() as current:
                version = current.execute('PRAGMA user_version').fetchone()[0]
                if version < 3:
                    with sqlite3.connect(str(self.path) + '.pre-v3.bak') as backup:
                        current.backup(backup)
        with self._write_lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
                    stage_message TEXT NOT NULL DEFAULT '',
                    title TEXT,
                    platform TEXT,
                    author TEXT,
                    duration REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    output_path TEXT,
                    job_dir TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
                    transcription_profile TEXT NOT NULL DEFAULT 'balanced',
                    llm_provider TEXT NOT NULL DEFAULT 'local'
                )"""
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "transcription_profile" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN transcription_profile TEXT NOT NULL DEFAULT 'balanced'")
            if "llm_provider" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN llm_provider TEXT NOT NULL DEFAULT 'local'")
            for name, declaration in {
                'input_type': "TEXT NOT NULL DEFAULT 'url'",
                'input_name': "TEXT NOT NULL DEFAULT ''",
                'processing_mode': "TEXT NOT NULL DEFAULT 'lecture'",
                'transcription_device': "TEXT NOT NULL DEFAULT 'gpu'",
            }.items():
                if name not in columns:
                    connection.execute(f'ALTER TABLE jobs ADD COLUMN {name} {declaration}')
            connection.execute('PRAGMA user_version = 3')
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_active_status ON jobs(status) WHERE status NOT IN ('completed','failed','canceled')")
            connection.execute("PRAGMA optimize")

    def create_job(
        self,
        job_id: str,
        url: str,
        job_dir: Path,
        transcription_profile: str = "balanced",
        llm_provider: str = "local",
        processing_mode: str = 'lecture',
        transcription_device: str = 'gpu',
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO jobs(id,url,status,progress,stage_message,created_at,updated_at,job_dir,transcription_profile,llm_provider,processing_mode,transcription_device) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, url, "queued", 0, "等待处理", now, now, str(job_dir), transcription_profile, llm_provider, processing_mode, transcription_device),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._serialize(row) if row else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at DESC, id DESC").fetchall()
        return [self._serialize(row) for row in rows]

    def update_job(self, job_id: str, **values: Any) -> None:
        allowed = {"status","progress","stage_message","title","platform","author","duration","error_code","error_message","output_path","attempt","cancel_requested","input_type","input_name"}
        allowed.update({'processing_mode', 'llm_provider', 'transcription_device'})
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._write_lock, self.connect() as connection:
            connection.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*values.values(), job_id))

    def mark_interrupted(self) -> None:
        now = utc_now()
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self._write_lock, self.connect() as connection:
            connection.execute(
                f"UPDATE jobs SET status='failed', error_code='INTERRUPTED', error_message='上次处理被程序退出中断，可点击重试', stage_message='处理已中断', updated_at=? WHERE status IN ({placeholders})",
                (now, *ACTIVE_STATUSES),
            )

    def reset_for_retry(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if not job or job["status"] not in {"failed", "canceled"}:
            return None
        self.update_job(job_id, status="queued", progress=0, stage_message="等待重试", error_code=None, error_message=None, output_path=None, cancel_requested=0, attempt=int(job["attempt"])+1)
        return self.get_job(job_id)

    def delete_job(self, job_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            result = connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return result.rowcount > 0

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["cancel_requested"] = bool(data["cancel_requested"])
        return data
