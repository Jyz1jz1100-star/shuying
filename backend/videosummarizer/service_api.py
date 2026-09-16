"""Versioned remote API. Never mounts the desktop application or its controls."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import shutil
import threading
import time
import uuid
from dataclasses import replace
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .database import ACTIVE_STATUSES, Database
from .exports import export_workspace
from .learning import LearningPipeline, workspace_lock
from .llm_settings import LLMSettingsError, LLMSettingsStore
from .manager import JobManager
from .materials import import_material

log = logging.getLogger(__name__)
EXPORTS = {'md': 'text/markdown', 'outline': 'text/markdown', 'txt': 'text/plain',
           'vtt': 'text/vtt', 'srt': 'application/x-subrip', 'json': 'application/json',
           'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


class KeyStore:
    """Only SHA256 digests of high-entropy client tokens belong in this file."""
    def __init__(self, path: Path):
        self.path = path

    def identify(self, token: str) -> str | None:
        if not 32 <= len(token) <= 256:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        try:
            records = json.loads(self.path.read_text(encoding='utf-8'))['keys']
            for item in records:
                if hmac.compare_digest(digest, item['sha256']) and not item.get('revoked', False):
                    return str(item['id'])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None


class JobView(BaseModel):
    id: str
    status: str
    progress: int
    title: str | None = None
    created_at: str
    updated_at: str
    processing_mode: str
    error_code: str | None = None


class JobPage(BaseModel):
    items: list[JobView]
    total: int
    offset: int
    limit: int


class NotesRequest(BaseModel):
    proofread: bool = False


class LinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    mode: Literal['transcript', 'lecture'] = 'transcript'
    device: Literal['cpu', 'gpu'] = 'gpu'


def create_service(config: Settings, keys: KeyStore, *, start_worker: bool = True,
                   allowed_origins: tuple[str, ...] = (), max_jobs: int = 50,
                   max_active: int = 4, requests_per_minute: int = 120) -> FastAPI:
    config.ensure_directories()
    db = Database(config.db_path)
    db.initialize()
    with db.connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS api_owners (job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE, key_id TEXT NOT NULL)')
        connection.execute('CREATE INDEX IF NOT EXISTS api_owners_key ON api_owners(key_id)')
    store = LLMSettingsStore(config.llm_settings_path, config.ollama_model)
    pipeline = LearningPipeline(replace(config, restricted_video_links=True), db, store)
    manager = JobManager(db, pipeline)
    mutation_lock = asyncio.Lock()
    buckets: dict[str, deque] = {}
    bucket_lock = threading.Lock()
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(_):
        if start_worker:
            manager.start()
        try:
            yield
        finally:
            if start_worker:
                manager.stop()

    app = FastAPI(title='Shuying API', version='1.0.0', lifespan=lifespan,
                  description='Upload media/subtitles, poll jobs, retrieve transcripts and export documents. Bearer keys isolate client jobs.',
                  redoc_url=None)
    app.state.database, app.state.pipeline, app.state.manager = db, pipeline, manager

    @app.get('/', include_in_schema=False, response_class=HTMLResponse)
    def mobile_home():
        from .mobile_page import HTML
        return HTMLResponse(HTML, headers={
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'})

    @app.get('/mobile.js', include_in_schema=False)
    def mobile_script():
        from .mobile_page import JS
        return Response(JS, media_type='application/javascript')

    if allowed_origins:
        if '*' in allowed_origins:
            raise ValueError('Configure explicit browser origins, not a wildcard')
        app.add_middleware(CORSMiddleware, allow_origins=list(allowed_origins),
                           allow_credentials=False, allow_methods=['GET', 'POST', 'DELETE'],
                           allow_headers=['Authorization', 'Content-Type'],
                           expose_headers=['Content-Disposition', 'Retry-After'])

    @app.exception_handler(HTTPException)
    async def http_error(_, exc):
        return JSONResponse({'error': {'code': f'HTTP_{exc.status_code}', 'message': str(exc.detail)}},
                            status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc):
        return JSONResponse({'error': {'code': 'INVALID_REQUEST', 'message': 'Invalid request parameters',
                                      'fields': ['.'.join(map(str, e['loc'])) for e in exc.errors()]}}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(_, exc):
        log.error('API request failed', exc_info=exc)
        return JSONResponse({'error': {'code': 'INTERNAL_ERROR', 'message': 'Request failed; consult the server operator'}}, status_code=500)

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        key_id = keys.identify(credentials.credentials) if credentials and credentials.scheme.lower() == 'bearer' else None
        if not key_id:
            raise HTTPException(401, 'A valid Bearer API key is required', headers={'WWW-Authenticate': 'Bearer'})
        now = time.monotonic()
        with bucket_lock:
            bucket = buckets.setdefault(key_id, deque())
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= requests_per_minute:
                raise HTTPException(429, 'Request rate exceeded', headers={'Retry-After': '60'})
            bucket.append(now)
        return key_id

    def owned(job_id: str, key_id: str) -> dict:
        with db.connect() as connection:
            row = connection.execute('SELECT j.* FROM jobs j JOIN api_owners o ON j.id=o.job_id WHERE j.id=? AND o.key_id=?', (job_id, key_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Job not found')
        if Path(row['job_dir']).resolve() != (config.jobs_dir / row['id']).resolve():
            raise HTTPException(500, 'Invalid job storage location; contact the operator')
        return dict(row)

    def available(job):
        if job['status'] in ACTIVE_STATUSES or manager.active_job_id == job['id']:
            raise HTTPException(409, 'Job is still active')

    def notes_provider():
        provider = store.public()['default_provider']
        try:
            store.runtime(provider)
        except (LLMSettingsError, OSError):
            raise HTTPException(503, 'Notes model is not configured; contact the operator')
        return provider

    def capacity(new_job: bool = False):
        with db.connect() as connection:
            total = connection.execute('SELECT count(*) FROM jobs').fetchone()[0]
            active = connection.execute('SELECT count(*) FROM jobs WHERE status IN ("queued","probing","downloading","transcribing","proofreading","summarizing","rendering")').fetchone()[0]
        if new_job and total >= max_jobs:
            raise HTTPException(409, 'Storage job limit reached; delete completed jobs first')
        if active >= max_active:
            raise HTTPException(429, 'Processing queue is full', headers={'Retry-After': '30'})
        if shutil.disk_usage(config.data_dir).free < 1024**3:
            raise HTTPException(507, 'Insufficient free disk space')

    @app.get('/healthz', tags=['Service'])
    def healthz():
        return {'status': 'ok', 'api_version': 'v1'}

    @app.get('/v1/capabilities', tags=['Service'])
    def capabilities(key_id: str = Depends(authenticate)):
        return {'api_version': 'v1', 'inputs': ['srt', 'vtt', 'mp4', 'mkv', 'webm', 'mov', 'mp3', 'wav', 'm4a', 'flac'],
                'exports': list(EXPORTS), 'max_upload_bytes': config.max_download_bytes,
                'max_subtitle_bytes': min(config.max_download_bytes, 10 * 1024**2),
                'max_duration_seconds': config.max_duration_seconds, 'max_active_jobs': max_active,
                'max_retained_jobs': max_jobs, 'requests_per_minute': requests_per_minute,
                'url_import': True, 'url_sites': ['bilibili', 'youtube'],
                'notes': {'provider': store.public()['default_provider'],
                          'model': store.public()['api_model'] if store.public()['default_provider'] == 'openai_compatible' else store.public()['local_model']}}

    @app.post('/v1/jobs', response_model=JobView, status_code=202, tags=['Jobs'],
              summary='Upload a file as raw bytes; processing is asynchronous',
              openapi_extra={'requestBody': {'required': True, 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
    async def upload(request: Request, filename: str = Query(min_length=1, max_length=180),
                     mode: Literal['transcript', 'lecture'] = 'transcript',
                     device: Literal['cpu', 'gpu'] = 'gpu', key_id: str = Depends(authenticate)):
        if '/' in filename or '\\' in filename or ':' in filename or any(ord(c) < 32 for c in filename):
            raise HTTPException(400, 'filename must be a plain file name')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/octet-stream':
            raise HTTPException(415, 'Send raw file bytes as application/octet-stream')
        if request.headers.get('content-encoding', 'identity') != 'identity':
            raise HTTPException(415, 'Compressed request bodies are not supported')
        limit = min(config.max_download_bytes, 10 * 1024**2) if Path(filename).suffix.lower() in {'.srt', '.vtt'} else config.max_download_bytes
        length = request.headers.get('content-length')
        if length and (not length.isdigit() or int(length) > limit):
            raise HTTPException(413, 'Upload exceeds the size limit')
        if mutation_lock.locked():
            raise HTTPException(429, 'Another mutation is in progress', headers={'Retry-After': '5'})
        async with mutation_lock:
            capacity(new_job=True)
            # Import first without enqueuing, so ownership is durable before processing.
            try:
                async with asyncio.timeout(120):
                    job = await import_material(request, filename, database=db,
                        manager=SimpleNamespace(enqueue=lambda _: None), settings=config,
                        processing_mode=mode, transcription_device=device, owner_id=key_id, transcription_profile='accurate',
                        llm_provider=notes_provider() if mode == 'lecture' else store.public()['default_provider'])
            except TimeoutError:
                raise HTTPException(408, 'Upload timed out')
            manager.enqueue(job['id'])
            return job

    @app.post('/v1/jobs/link', response_model=JobView, status_code=202, tags=['Jobs'])
    async def import_link(body: LinkRequest, key_id: str = Depends(authenticate)):
        from .video_links import normalize_video_link
        from .security import UnsafeUrlError
        try:
            url = await run_in_threadpool(normalize_video_link, body.url)
        except UnsafeUrlError as exc:
            raise HTTPException(400, str(exc)) from None
        async with mutation_lock:
            capacity(new_job=True)
            provider = notes_provider() if body.mode == 'lecture' else store.public()['default_provider']
            job_id = uuid.uuid4().hex
            directory = config.jobs_dir / job_id
            directory.mkdir()
            try:
                job = db.create_job(job_id, url, directory, 'accurate', provider, body.mode, body.device, owner_id=key_id)
            except Exception:
                directory.rmdir()
                raise
            manager.enqueue(job_id)
            return job

    @app.get('/v1/jobs', response_model=JobPage, tags=['Jobs'])
    def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), key_id: str = Depends(authenticate)):
        with db.connect() as connection:
            total = connection.execute('SELECT count(*) FROM api_owners WHERE key_id=?', (key_id,)).fetchone()[0]
            rows = connection.execute('SELECT j.* FROM jobs j JOIN api_owners o ON j.id=o.job_id WHERE o.key_id=? ORDER BY j.created_at DESC,j.id DESC LIMIT ? OFFSET ?', (key_id, limit, offset)).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit}

    @app.get('/v1/jobs/{job_id}', response_model=JobView, tags=['Jobs'])
    def job_status(job_id: str, key_id: str = Depends(authenticate)):
        return owned(job_id, key_id)

    @app.get('/v1/jobs/{job_id}/result', tags=['Results'])
    def result(job_id: str, key_id: str = Depends(authenticate)):
        job = owned(job_id, key_id)
        state = pipeline.state(job)
        if not state['segments']:
            raise HTTPException(409, 'Transcript is not ready; poll job status')
        return {'job_id': job_id, 'title': job['title'], 'revision': state['revision'],
                'segments': [{k: s[k] for k in ('id','start','end','original','text','review','flags') if k in s} for s in state['segments']],
                'blocks': state['blocks'], 'glossary': state['glossary']}

    @app.get('/v1/jobs/{job_id}/export', tags=['Results'])
    def export(job_id: str, format: Literal['md','docx','txt','vtt','srt','json','outline'] = 'md', key_id: str = Depends(authenticate)):
        job = owned(job_id, key_id)
        with workspace_lock:
            state = pipeline.state(job)
            if not state['segments']:
                raise HTTPException(409, 'Transcript is not ready')
            path = export_workspace(state, job, format)
            return Response(path.read_bytes(), media_type=EXPORTS[format], headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(path.name)})

    @app.post('/v1/jobs/{job_id}/cancel', response_model=JobView, tags=['Jobs'])
    async def cancel(job_id: str, key_id: str = Depends(authenticate)):
        async with mutation_lock:
            job = owned(job_id, key_id)
            if job['status'] not in ACTIVE_STATUSES:
                return job
            manager.cancel(job_id)
            return owned(job_id, key_id)

    @app.post('/v1/jobs/{job_id}/retry', response_model=JobView, status_code=202, tags=['Jobs'])
    async def retry(job_id: str, key_id: str = Depends(authenticate)):
        async with mutation_lock:
            job = owned(job_id, key_id)
            available(job)
            capacity()
            retried = manager.retry(job_id)
            if not retried:
                raise HTTPException(409, 'Only failed or canceled jobs can be retried')
            return retried

    @app.post('/v1/jobs/{job_id}/notes', response_model=JobView, status_code=202, tags=['Jobs'])
    async def notes(job_id: str, body: NotesRequest, key_id: str = Depends(authenticate)):
        from .checkpoints import atomic_json
        async with mutation_lock:
            job = owned(job_id, key_id)
            available(job)
            capacity()
            if not pipeline.state(job)['segments']:
                raise HTTPException(409, 'Transcript is not ready')
            provider = notes_provider()
            atomic_json(Path(job['job_dir']) / 'request.json', {'proofread': body.proofread, 'llm_provider': provider})
            db.update_job(job_id, processing_mode='lecture', llm_provider=provider, status='queued', progress=0, cancel_requested=0,
                          error_code=None, error_message=None, stage_message='等待整理笔记')
            manager.enqueue(job_id)
            return owned(job_id, key_id)

    @app.delete('/v1/jobs/{job_id}', status_code=204, tags=['Jobs'])
    async def delete(job_id: str, key_id: str = Depends(authenticate)):
        async with mutation_lock:
            job = owned(job_id, key_id)
            available(job)
            if not manager.delete(job_id):
                raise HTTPException(409, 'Job cannot be deleted while active')
            return Response(status_code=204)

    return app
