from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .article_docx_builder import build_article_docx
from .database import Database
from .docx_builder import build_docx
from .llm_settings import LLMSettingsError, LLMSettingsStore
from .schemas import SourceMetadata, Transcript
from .security import validate_public_url
from .summarizer import OllamaSummarizer
from .subtitle_builder import build_srt
from .text_utils import parse_subtitle
from .whispercpp import WhisperCppError, WhisperCppTranscriber


logger = logging.getLogger(__name__)


class JobCancelled(RuntimeError):
    pass


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Pipeline:
    def __init__(self, config: Settings, database: Database, llm_settings: LLMSettingsStore):
        self.config = config
        self.database = database
        self.llm_settings = llm_settings
        self.transcriber = WhisperCppTranscriber(config)

    def run(self, job_id: str) -> Path:
        job = self.database.get_job(job_id)
        if not job:
            raise PipelineError("JOB_NOT_FOUND", "任务不存在")
        job_dir = Path(job["job_dir"])
        job_dir.mkdir(parents=True, exist_ok=True)
        try:
            runtime = self.llm_settings.runtime(str(job.get("llm_provider") or "local"))
        except LLMSettingsError as exc:
            raise PipelineError("LLM_CONFIG_INVALID", str(exc)) from exc
        summarizer = OllamaSummarizer(self.config, runtime)
        try:
            self._update(job_id, "probing", 1, "正在检查视频链接")
            info = self._probe(job_id, job["url"])
            metadata = self._metadata(info, job["url"])
            metadata.llm_model = runtime.label
            self.database.update_job(job_id, title=metadata.video_title, platform=metadata.platform, author=metadata.author, duration=metadata.duration_seconds)
            (job_dir / "metadata.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
            self._check_cancel(job_id)
            summarizer.ensure_model(
                lambda progress, message: self._update(job_id, "probing", progress, message),
                lambda: self._check_cancel(job_id),
            )

            transcript = self._subtitle_transcript(job_id, job["url"], info, job_dir)
            if transcript is None:
                audio_path = self._download_audio(job_id, job["url"], job_dir)
                summarizer.unload_model()
                transcript = self._transcribe(job_id, audio_path, str(job.get("transcription_profile") or "balanced"), job_dir)
            metadata.transcript_language = transcript.language
            if transcript.source == "human_subtitles":
                metadata.transcription_method = "视频作者字幕"
            else:
                profile = str(job.get("transcription_profile") or "balanced")
                metadata.transcription_method = "Whisper large-v3（Vulkan）" if profile == "accurate" else "Whisper large-v3-turbo（Vulkan）"
            (job_dir / "transcript_raw.json").write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
            if transcript.source != "human_subtitles":
                self._check_cancel(job_id)
                self._update(job_id, "proofreading", 59, f"正在用 {runtime.label} 校对字幕")
                transcript = summarizer.proofread(
                    transcript,
                    lambda progress, message: self._update(job_id, "proofreading", progress, message),
                    lambda: self._check_cancel(job_id),
                )
                metadata.transcription_method += f"；{runtime.label} 校对"
            (job_dir / "transcript.json").write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
            build_srt(transcript, metadata.video_title, job_dir)

            self._check_cancel(job_id)
            self._update(job_id, "summarizing", 69, f"正在用 {runtime.label} 整理内容")
            summary = summarizer.summarize(transcript, metadata, lambda progress, message: self._update(job_id, "summarizing", progress, message), lambda: self._check_cancel(job_id))
            (job_dir / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")

            self._check_cancel(job_id)
            article = summarizer.write_article(
                transcript,
                metadata,
                summary,
                lambda progress, message: self._update(job_id, "summarizing", progress, message),
                lambda: self._check_cancel(job_id),
            )
            (job_dir / "article.json").write_text(article.model_dump_json(indent=2), encoding="utf-8")
            build_article_docx(article, job_dir)

            self._check_cancel(job_id)
            self._update(job_id, "rendering", 96, "正在生成并校验 Word 文档")
            output = build_docx(summary, job_dir)
            self._cleanup_media(job_dir)
            self.database.update_job(job_id, status="completed", progress=100, stage_message="总结、字幕和完整文章已生成", output_path=str(output), error_code=None, error_message=None)
            return output
        except JobCancelled:
            self._cleanup_media(job_dir)
            self.database.update_job(job_id, status="canceled", progress=0, stage_message="任务已取消", error_code=None, error_message=None)
            raise
        except PipelineError:
            self._cleanup_media(job_dir)
            raise
        except Exception as exc:
            self._cleanup_media(job_dir)
            logger.exception("任务 %s 处理失败", job_id)
            raise PipelineError("PROCESSING_FAILED", str(exc) or exc.__class__.__name__) from exc
        finally:
            summarizer.unload_model()

    def _probe(self, job_id: str, url: str) -> dict[str, Any]:
        validate_public_url(url)
        self._update(job_id, "probing", 5, "正在读取视频标题、作者和时长")
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError

            with YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True, "socket_timeout": 30, "retries": 2}) as ydl:
                raw = ydl.extract_info(url, download=False)
                info = ydl.sanitize_info(raw)
        except Exception as exc:
            message = str(exc)
            if "login" in message.lower() or "sign in" in message.lower() or "会员" in message:
                raise PipelineError("LOGIN_REQUIRED", "该视频需要登录、会员或额外权限，首版暂不支持") from exc
            raise PipelineError("UNSUPPORTED_URL", f"无法读取该公开视频：{message}") from exc
        if not info:
            raise PipelineError("UNSUPPORTED_URL", "链接中没有可处理的视频")
        if info.get("_type") in {"playlist", "multi_video"} or info.get("entries"):
            raise PipelineError("PLAYLIST_NOT_SUPPORTED", "首版只处理单个视频，不支持播放列表或合集")
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            raise PipelineError("LIVE_NOT_SUPPORTED", "首版不支持直播或预约直播")
        duration = float(info.get("duration") or 0)
        if duration <= 0:
            raise PipelineError("NO_DURATION", "无法确认视频时长，已为安全起见停止处理")
        if duration > self.config.max_duration_seconds:
            raise PipelineError("DURATION_LIMIT", "视频超过 2 小时限制")
        final_url = info.get("webpage_url")
        if final_url:
            validate_public_url(final_url)
        return info

    def _metadata(self, info: dict[str, Any], source_url: str) -> SourceMetadata:
        platform = str(info.get("extractor_key") or info.get("extractor") or "公开媒体")
        return SourceMetadata(
            video_title=str(info.get("title") or "未命名视频"),
            platform=platform,
            author=str(info.get("uploader") or info.get("channel") or "未知"),
            duration_seconds=float(info.get("duration") or 0),
            source_url=source_url,
            transcript_language="unknown",
        )

    def _subtitle_transcript(self, job_id: str, url: str, info: dict[str, Any], job_dir: Path) -> Transcript | None:
        subtitles = info.get("subtitles") or {}
        if not subtitles:
            return None
        preferences = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "en", "en-US")
        language = next((item for item in preferences if item in subtitles), next(iter(subtitles), None))
        if not language:
            return None
        self._update(job_id, "downloading", 22, f"检测到作者字幕，正在读取 {language} 字幕")
        try:
            from yt_dlp import YoutubeDL

            template = str(job_dir / "subtitle.%(ext)s")
            options = {
                "quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
                "writesubtitles": True, "writeautomaticsub": False, "subtitleslangs": [language],
                "subtitlesformat": "vtt/srt/best", "outtmpl": template, "socket_timeout": 30,
            }
            with YoutubeDL(options) as ydl:
                ydl.download([url])
            candidates = sorted([path for path in job_dir.glob("subtitle*") if path.suffix.lower() in {".vtt", ".srt"}])
            if not candidates:
                return None
            segments = parse_subtitle(candidates[0])
            if not segments:
                return None
            return Transcript(language=language, source="human_subtitles", segments=segments)
        except Exception:
            return None

    def _download_audio(self, job_id: str, url: str, job_dir: Path) -> Path:
        self._update(job_id, "downloading", 24, "未找到作者字幕，正在下载最佳音轨")
        try:
            from yt_dlp import YoutubeDL

            def hook(payload: dict[str, Any]) -> None:
                self._check_cancel(job_id)
                if payload.get("status") == "downloading":
                    total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
                    downloaded = payload.get("downloaded_bytes") or 0
                    if downloaded > self.config.max_download_bytes:
                        raise PipelineError("DOWNLOAD_LIMIT", "下载数据超过 2GB 限制")
                    if total:
                        self._update(job_id, "downloading", 24 + int(12 * min(1, downloaded / total)), f"正在下载音轨 {int(downloaded/total*100)}%")

            options = {
                "format": "bestaudio/best", "outtmpl": str(job_dir / "source.%(ext)s"), "noplaylist": True,
                "quiet": True, "no_warnings": True, "socket_timeout": 30, "retries": 2,
                "max_filesize": self.config.max_download_bytes, "progress_hooks": [hook],
            }
            with YoutubeDL(options) as ydl:
                ydl.download([url])
        except JobCancelled:
            raise
        except PipelineError:
            raise
        except Exception as exc:
            if self.database.get_job(job_id).get("cancel_requested"):
                raise JobCancelled from exc
            raise PipelineError("DOWNLOAD_FAILED", f"音轨下载失败：{exc}") from exc
        candidates = [path for path in job_dir.glob("source.*") if path.is_file() and not path.name.endswith((".part", ".ytdl"))]
        if not candidates:
            raise PipelineError("DOWNLOAD_FAILED", "未生成可转写的音轨文件")
        return max(candidates, key=lambda path: path.stat().st_size)

    def _transcribe(self, job_id: str, audio_path: Path, profile: str, job_dir: Path) -> Transcript:
        device = (self.database.get_job(job_id) or {}).get('transcription_device', 'gpu')
        profile_label = "高精度 large-v3" if profile == "accurate" else "均衡 large-v3-turbo"
        self._update(job_id, "transcribing", 37, f"正在启动 Whisper Vulkan（{profile_label}）")
        try:
            return self.transcriber.transcribe(
                audio_path,
                profile,
                lambda progress, message: self._update(job_id, "transcribing", progress, message),
                lambda: self._check_cancel(job_id),
                job_dir,
                device=device,
            )
        except JobCancelled:
            raise
        except WhisperCppError as exc:
            raise PipelineError("TRANSCRIPTION_FAILED", str(exc)) from exc
        except Exception as exc:
            raise PipelineError("TRANSCRIPTION_FAILED", f"本地 Vulkan 语音转写失败：{exc}") from exc

    def _update(self, job_id: str, status: str, progress: int, message: str) -> None:
        self.database.update_job(job_id, status=status, progress=max(0, min(100, progress)), stage_message=message)

    def _check_cancel(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if not job or job.get("cancel_requested"):
            raise JobCancelled

    @staticmethod
    def _cleanup_media(job_dir: Path) -> None:
        for path in job_dir.iterdir() if job_dir.exists() else []:
            if path.name.startswith(("source.", "subtitle.", "transcribe.")) or path.suffix in {".part", ".ytdl"}:
                try:
                    path.unlink()
                except OSError:
                    pass
