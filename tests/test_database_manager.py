import time
import sqlite3
from pathlib import Path
from videosummarizer.database import Database
from videosummarizer.manager import JobManager


class FakePipeline:
    def __init__(self, database: Database): self.database = database
    def run(self, job_id: str):
        self.database.update_job(job_id, status="completed", progress=100, stage_message="完成")
        return Path("result.docx")


def test_serial_job_lifecycle(tmp_path):
    database = Database(tmp_path / "jobs.sqlite3"); database.initialize()
    job_dir = tmp_path / "jobs" / "one"; job_dir.mkdir(parents=True)
    created = database.create_job("one", "https://example.com/video", job_dir, "accurate", "openai_compatible")
    assert created["transcription_profile"] == "accurate"
    assert created["llm_provider"] == "openai_compatible"
    manager = JobManager(database, FakePipeline(database)); manager.start(); manager.enqueue("one")
    deadline = time.time() + 3
    while time.time() < deadline and database.get_job("one")["status"] != "completed": time.sleep(0.02)
    manager.stop()
    assert database.get_job("one")["status"] == "completed"
    assert manager.delete("one") is True
    assert database.get_job("one") is None


def test_existing_database_gets_transcription_profile_column(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE jobs (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, status TEXT NOT NULL,
                progress INTEGER NOT NULL, stage_message TEXT NOT NULL,
                title TEXT, platform TEXT, author TEXT, duration REAL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                error_code TEXT, error_message TEXT, output_path TEXT,
                job_dir TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1,
                cancel_requested INTEGER NOT NULL DEFAULT 0
            )"""
        )
    database = Database(path)
    database.initialize()
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
    assert "transcription_profile" in columns
    assert "llm_provider" in columns
