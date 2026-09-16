from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "VideoSummarizer"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("VIDEOSUMMARIZER_DATA_DIR", str(_default_data_dir())))
    host: str = "127.0.0.1"
    port: int = int(os.environ.get("VIDEOSUMMARIZER_PORT", "8765"))
    ollama_url: str = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "qwen3.5:9b-q4_K_M")
    max_duration_seconds: int = 2 * 60 * 60
    max_download_bytes: int = 2 * 1024 * 1024 * 1024
    chunk_seconds: int = 15 * 60
    chunk_characters: int = 12_000
    cpu_threads: int = 6
    transcription_chunk_seconds: int = 90
    transcription_overlap_seconds: float = 1.5

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.sqlite3"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def llm_settings_path(self) -> Path:
        return self.data_dir / "llm_settings.json"

    @property
    def frontend_dir(self) -> Path:
        bundled = resource_path("frontend_dist")
        if bundled.exists():
            return bundled
        return Path(__file__).resolve().parents[2] / "frontend_dist"

    @property
    def whisper_runtime_dir(self) -> Path:
        bundled = resource_path("whispercpp")
        if bundled.exists():
            return bundled
        return Path(__file__).resolve().parents[2] / "vendor" / "whispercpp" / "runtime"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
