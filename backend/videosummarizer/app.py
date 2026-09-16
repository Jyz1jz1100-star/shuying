from __future__ import annotations

import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .config import settings
from .article_docx_builder import build_article_docx
from .database import ACTIVE_STATUSES, Database
from .manager import JobManager
from .live_subtitles import LiveSubtitleManager
from .llm_settings import LLMSettingsError, LLMSettingsStore
from .learning import LearningPipeline
from .workspace_api import router_for
from urllib.parse import urlsplit
from .schemas import (
    CreateJobRequest,
    StartLiveSubtitlesRequest,
    TestLLMSettingsRequest,
    Transcript,
    UpdateLLMSettingsRequest,
    VideoSummary,
)
from .security import UnsafeUrlError, validate_public_url
from .summarizer import OllamaError, OllamaSummarizer
from .subtitle_builder import build_srt


settings.ensure_directories()
database = Database(settings.db_path)
llm_settings = LLMSettingsStore(settings.llm_settings_path, settings.ollama_model)
pipeline = LearningPipeline(settings, database, llm_settings)
manager = JobManager(database, pipeline)
live_subtitles = LiveSubtitleManager(settings)
article_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    manager.start()
    yield
    live_subtitles.stop()
    manager.stop()


app = FastAPI(title="述影", version="2.0.0a1", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def loopback_only(request: Request, call_next):
    client = request.client.host if request.client else "127.0.0.1"
    if client not in {"127.0.0.1", "::1", "testclient"}:
        return JSONResponse(status_code=403, content={"detail": "仅允许本机访问"})
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse(status_code=403, content={'detail': '拒绝跨站写入'})
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            # Vite development proxy on the loopback interface only.
            if origin not in {'http://localhost:3000', 'http://127.0.0.1:3000'}:
                return JSONResponse(status_code=403, content={'detail': '拒绝跨站写入'})
    return await call_next(request)


@app.get("/api/health")
def health():
    ollama_ready, model_ready = OllamaSummarizer(settings).health()
    llm_public = llm_settings.public()
    api_ready = bool(llm_public["api_model"] and llm_public["has_api_key"])
    selected_llm_ready = model_ready if llm_public["default_provider"] == "local" else api_ready
    disk = shutil.disk_usage(settings.data_dir)
    whisper_runtime_ready = pipeline.transcriber.runtime_ready()
    return {
        "ok": selected_llm_ready and whisper_runtime_ready and disk.free >= 8 * 1024**3,
        "ollama_ready": ollama_ready,
        "model_ready": model_ready,
        "model": settings.ollama_model,
        "whisper_runtime_ready": whisper_runtime_ready,
        "whisper_backend": "Vulkan",
        "free_disk_gb": round(disk.free / 1024**3, 2),
        "active_job_id": manager.active_job_id,
        "live_subtitles_status": live_subtitles.snapshot()["status"],
        "default_llm_provider": llm_public["default_provider"],
        "api_llm_configured": api_ready,
    }


@app.get("/api/settings/llm")
def get_llm_settings():
    return llm_settings.public()


@app.put("/api/settings/llm")
def update_llm_settings(request: UpdateLLMSettingsRequest):
    try:
        return llm_settings.save(
            request.default_provider,
            request.api_base_url,
            request.api_model,
            request.api_key,
        )
    except (LLMSettingsError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/settings/llm/test")
def test_llm_settings(request: TestLLMSettingsRequest):
    if manager.active_job_id or live_subtitles.active:
        raise HTTPException(status_code=409, detail="请等待当前任务结束后再测试 LLM API")
    try:
        runtime = llm_settings.runtime_for_test(request.api_base_url, request.api_model, request.api_key)
        OllamaSummarizer(settings, runtime).test_connection()
        return {"ok": True, "message": f"连接成功：{runtime.model}"}
    except (LLMSettingsError, OllamaError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=400, detail=f"API 测试失败：{exc}") from exc


@app.post("/api/shutdown")
def shutdown_app(request: Request, background_tasks: BackgroundTasks):
    callback = getattr(request.app.state, "request_shutdown", None)
    if callback is None:
        raise HTTPException(status_code=503, detail="当前运行方式不支持从页面退出")
    background_tasks.add_task(callback)
    return {"shutting_down": True}


@app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(request: CreateJobRequest):
    if live_subtitles.active:
        raise HTTPException(status_code=409, detail="请先停止实时字幕，再创建视频总结任务")
    try:
        url = validate_public_url(str(request.url))
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail={"code": "UNSAFE_URL", "message": str(exc)}) from exc
    try:
        llm_settings.runtime(request.llm_provider)
    except LLMSettingsError as exc:
        raise HTTPException(status_code=400, detail={"code": "LLM_CONFIG_INVALID", "message": str(exc)}) from exc
    job_id = uuid.uuid4().hex
    job_dir = settings.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    job = database.create_job(job_id, url, job_dir, request.transcription_profile, request.llm_provider)
    manager.enqueue(job_id)
    return job


@app.get("/api/live/devices")
def live_devices():
    return {"devices": live_subtitles.list_devices()}


@app.get("/api/live")
def live_state():
    return live_subtitles.snapshot()


@app.post("/api/live/start")
def start_live_subtitles(request: StartLiveSubtitlesRequest):
    if manager.active_job_id or any(job["status"] in ACTIVE_STATUSES for job in database.list_jobs()):
        raise HTTPException(status_code=409, detail="请等待视频总结任务结束，再启动实时字幕")
    try:
        return live_subtitles.start(request.device_id, request.transcription_profile)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/live/stop")
def stop_live_subtitles():
    return live_subtitles.stop()


@app.get("/api/jobs")
def list_jobs():
    return database.list_jobs()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not manager.cancel(job_id):
        raise HTTPException(status_code=409, detail="任务当前不可取消")
    return database.get_job(job_id)


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    job = manager.retry(job_id)
    if not job:
        raise HTTPException(status_code=409, detail="只有失败或已取消任务可以重试")
    return job


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str):
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if (Path(job['job_dir']) / 'workspace.json').exists():
        from .exports import export_workspace
        from .learning import workspace_lock
        with workspace_lock:
            state = pipeline.state(job)
            if not state['blocks']:
                raise HTTPException(409, '讲义尚未生成')
            path = export_workspace(state, job, 'docx')
            return FileResponse(path, filename=path.name)
    if job["status"] != "completed" or not job["output_path"]:
        raise HTTPException(status_code=409, detail="总结文档尚未生成")
    path = Path(job["output_path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="总结文档已不存在")
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=path.name)


@app.get("/api/jobs/{job_id}/subtitle")
def download_subtitle(job_id: str):
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="字幕尚未生成")
    job_dir = Path(job["job_dir"])
    candidates = sorted(job_dir.glob("*_完整字幕_*.srt"), key=lambda path: path.stat().st_mtime, reverse=True)
    if candidates:
        path = candidates[0]
    else:
        transcript_path = job_dir / "transcript.json"
        if not transcript_path.is_file():
            raise HTTPException(status_code=410, detail="该任务的完整转写已不存在")
        try:
            transcript = Transcript.model_validate_json(transcript_path.read_text(encoding="utf-8"))
            path = build_srt(transcript, str(job.get("title") or "视频"), job_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"字幕生成失败：{exc}") from exc
    return FileResponse(path, media_type="application/x-subrip; charset=utf-8", filename=path.name)


@app.get("/api/jobs/{job_id}/article")
def download_article(job_id: str):
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    directory = Path(job["job_dir"])
    if (directory / "workspace.json").exists():
        from .exports import export_workspace
        from .learning import workspace_lock
        with workspace_lock:
            path = export_workspace(pipeline.state(job), job, 'docx')
            return FileResponse(path, filename=path.name)
    paths = sorted(directory.glob("*_完整文章_*.docx"))
    if not paths:
        raise HTTPException(409, "旧任务未生成文章，请在工作区主动重新生成")
    return FileResponse(paths[-1], filename=paths[-1].name)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="请先取消正在处理的任务")
    if not manager.delete(job_id):
        raise HTTPException(status_code=500, detail="删除任务失败")
    return {"deleted": True}


app.include_router(router_for(database, pipeline, manager, live_subtitles, settings))

if settings.frontend_dir.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
