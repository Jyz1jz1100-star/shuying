from __future__ import annotations

import copy
import shutil
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import av
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .checkpoints import Checkpoints, atomic_json, file_fingerprint
from .database import ACTIVE_STATUSES
from .evidence import apply_edit
from .exports import export_workspace
from .learning import workspace_lock
from .llm_settings import LLMSettingsError
from .config import resource_path
from .security import validate_public_url, UnsafeUrlError
from .text_utils import parse_subtitle


class SegmentEdit(BaseModel):
    revision: int = Field(ge=1)
    text: str | None = Field(default=None, min_length=1, max_length=3000)
    decision: Literal['accept', 'reject'] | None = None


class GlossaryEdit(BaseModel):
    revision: int = Field(ge=1)
    terms: list[str] = Field(max_length=200)


class Regenerate(BaseModel):
    proofread: bool = False
    llm_provider: Literal['local', 'openai_compatible'] | None = None


def media_files(directory):
    return [p for p in directory.iterdir() if p.is_file() and (p.name.startswith(('input.', 'source.')) and p.suffix not in {'.srt', '.vtt'} or p.name == 'transcribe.wav')]


def router_for(database, pipeline, manager, live, settings):
    router = APIRouter()

    def get_job(job_id):
        job = database.get_job(job_id)
        if not job:
            raise HTTPException(404, '任务不存在')
        return job

    def editable(job):
        if job['status'] in ACTIVE_STATUSES or manager.active_job_id == job['id']:
            raise HTTPException(409, '处理期间不能修改，请先取消或等待完成')

    def snapshot(job):
        state = pipeline.state(job)
        directory = Path(job['job_dir'])
        files = media_files(directory)
        return {**state, 'title': job.get('title') or '待处理材料', 'source_url': job['url'],
                'error_message': job.get('error_message') or '',
                'llm_provider': job.get('llm_provider', 'local'),
                'media_available': (directory / 'transcribe.wav').is_file(),
                'media_bytes': sum(p.stat().st_size for p in files),
                'busy': job['status'] in ACTIVE_STATUSES or manager.active_job_id == job['id'],
                'stage_status': [{'name': job['stage_message'], 'status': job['status']}],
                'checkpoints': Checkpoints(directory / 'checkpoints').status()}

    def version_check(state, revision):
        if revision != state['revision']:
            raise HTTPException(409, '内容已更新，请刷新后重新核对修改')

    @router.post('/api/import', status_code=202)
    async def import_file(request: Request, filename: str, llm_provider: Literal['local', 'openai_compatible'] = 'local',
                          transcription_profile: Literal['balanced', 'accurate'] = 'balanced', source_url: str = '',
                          processing_mode: Literal['transcript', 'lecture'] = 'lecture',
                          transcription_device: Literal['gpu', 'cpu'] = 'gpu'):
        if live.active:
            raise HTTPException(409, '请先停止实时字幕')
        suffix = Path(filename).suffix.lower()
        is_subtitle = suffix in {'.srt', '.vtt'}
        if suffix not in {'.srt', '.vtt', '.mp4', '.mkv', '.webm', '.mov', '.mp3', '.wav', '.m4a', '.flac'}:
            raise HTTPException(400, '不支持的文件格式')
        if source_url:
            try:
                source_url = validate_public_url(source_url)
            except UnsafeUrlError:
                raise HTTPException(400, '来源链接必须为公开视频链接')
        job_id = uuid.uuid4().hex
        directory = settings.jobs_dir / job_id
        directory.mkdir(parents=True)
        destination = directory / ('input' + suffix)
        limit = 10 * 1024**2 if is_subtitle else settings.max_download_bytes
        persisted = False
        try:
            size = 0
            with destination.open('wb') as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, '文件超过大小限制（字幕 10MB，媒体 2GB）')
                    if shutil.disk_usage(directory).free < len(chunk) + 128 * 1024**2:
                        raise HTTPException(507, '磁盘空间不足')
                    output.write(chunk)
            if is_subtitle:
                destination.read_text(encoding='utf-8-sig', errors='strict')
                segments = parse_subtitle(destination)
                if not segments:
                    raise HTTPException(400, '字幕中没有有效时间段')
                if any(s.end < s.start for s in segments) or any(b.start < a.start for a, b in zip(segments, segments[1:])):
                    raise HTTPException(400, '字幕时间必须顺序排列')
                duration = max(s.end for s in segments)
            else:
                with av.open(str(destination)) as media:
                    if not media.streams.audio:
                        raise HTTPException(400, '文件没有可用音轨')
                    duration = float(media.duration or 0) / av.time_base
                    if duration <= 0:
                        stream = media.streams.audio[0]
                        duration = float((stream.duration or 0) * (stream.time_base or 0))
            if not 0 < duration <= settings.max_duration_seconds:
                raise HTTPException(400, '材料时长必须在 0–2 小时内')
            atomic_json(directory / 'input_metadata.json', {'sha256': file_fingerprint(destination), 'size': size})
            job = database.create_job(job_id, source_url, directory, transcription_profile, llm_provider, processing_mode, transcription_device)
            persisted = True
            database.update_job(job_id, input_type=suffix[1:] if is_subtitle else 'media', input_name=Path(filename).name,
                                title=Path(filename).stem[:180], duration=duration, platform='本地字幕' if is_subtitle else '本地媒体')
            result = database.get_job(job_id)
            manager.enqueue(job_id)
            return result
        except BaseException as exc:
            # The directory is a freshly generated UUID under jobs_dir, never user input.
            if not persisted and directory.resolve().parent == settings.jobs_dir.resolve():
                shutil.rmtree(directory, ignore_errors=True)
            if persisted:
                database.update_job(job_id, status='failed', error_code='IMPORT_FAILED', error_message='导入未完成，材料已保留，可重试')
            if isinstance(exc, HTTPException):
                raise
            if isinstance(exc, Exception):
                raise HTTPException(400, '无法读取材料，请检查格式、编码和音轨') from exc
            raise

    @router.post('/api/demo', status_code=201)
    def demo():
        # An original bundled subtitle: no media download, ASR, or model calls.
        directory = settings.jobs_dir / uuid.uuid4().hex
        directory.mkdir()
        shutil.copyfile(resource_path('examples/checkpoints.srt'), directory / 'input.srt')
        job = database.create_job(directory.name, '', directory, processing_mode='transcript')
        database.update_job(job['id'], title='示例：检查点与可信讲义', input_type='srt', platform='原创示例')
        pipeline.run(job['id'])
        return database.get_job(job['id'])

    @router.get('/api/jobs/{job_id}/workspace')
    def workspace(job_id: str):
        with workspace_lock:
            return snapshot(get_job(job_id))

    @router.patch('/api/jobs/{job_id}/segments/{segment_id}')
    def edit_segment(job_id: str, segment_id: str, request: SegmentEdit):
        with workspace_lock:
            job = get_job(job_id)
            editable(job)
            state = pipeline.state(job)
            version_check(state, request.revision)
            if request.text is None and request.decision is None:
                raise HTTPException(400, '缺少修改内容')
            if segment_id not in {s['id'] for s in state['segments']}:
                raise HTTPException(404, '字幕片段不存在')
            old = copy.deepcopy(state)
            try:
                state = apply_edit(state, segment_id, request.text, request.decision)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            next(s for s in state['segments'] if s['id'] == segment_id)['human_edited'] = True
            atomic_json(Path(job['job_dir']) / 'history' / f'revision-{old["revision"]}.json', old)
            pipeline.save(job, state)
            return snapshot(job)

    @router.put('/api/jobs/{job_id}/glossary')
    def glossary(job_id: str, request: GlossaryEdit):
        with workspace_lock:
            job = get_job(job_id)
            editable(job)
            state = pipeline.state(job)
            version_check(state, request.revision)
            terms = list(dict.fromkeys(t.strip() for t in request.terms if t.strip()))
            if terms == state['glossary']:
                return snapshot(job)
            if any(len(t) > 200 for t in terms):
                raise HTTPException(400, '每条术语最多 200 字符，可用“标准词 = 别名”格式')
            atomic_json(Path(job['job_dir']) / 'history' / f'revision-{state["revision"]}.json', state)
            state['glossary'] = terms
            state['revision'] += 1
            for block in state['blocks']:
                block['stale'] = True
            pipeline.save(job, state)
            return snapshot(job)

    @router.post('/api/jobs/{job_id}/regenerate', status_code=202)
    def regenerate(job_id: str, request: Regenerate):
        with workspace_lock:
            job = get_job(job_id)
            editable(job)
            if live.active:
                raise HTTPException(409, '请先停止实时字幕')
            if not pipeline.state(job)['segments']:
                raise HTTPException(409, '请先完成字幕导入或转写')
            provider = request.llm_provider or job.get('llm_provider') or 'local'
            try:
                pipeline.llm_settings.runtime(provider)
            except LLMSettingsError as exc:
                raise HTTPException(400, str(exc)) from exc
            atomic_json(Path(job['job_dir']) / 'request.json', request.model_dump())
            database.update_job(job_id, processing_mode='lecture', llm_provider=provider, status='queued', progress=0, cancel_requested=0, error_message=None, error_code=None, stage_message='等待继续处理')
            manager.enqueue(job_id)
            return database.get_job(job_id)

    @router.get('/api/jobs/{job_id}/media')
    def media(job_id: str):
        job = get_job(job_id)
        path = Path(job['job_dir']) / 'transcribe.wav'
        if not path.is_file():
            raise HTTPException(404, '无可回听音频；可使用来源链接或重新导入媒体')
        return FileResponse(path, media_type='audio/wav', headers={'Cache-Control': 'no-store'})

    @router.delete('/api/jobs/{job_id}/media')
    def clear_media(job_id: str):
        with workspace_lock:
            job = get_job(job_id)
            editable(job)
            if not pipeline.state(job)['segments']:
                raise HTTPException(409, '尚无可保留的字幕，请完成转写后再清理媒体')
            for path in media_files(Path(job['job_dir'])):
                try:
                    path.unlink()
                except OSError:
                    raise HTTPException(409, '媒体正在使用，请停止播放后再清理')
            return snapshot(job)

    @router.get('/api/jobs/{job_id}/export')
    def export(job_id: str, format: Literal['md', 'docx', 'json', 'srt', 'txt', 'vtt'] = 'md'):
        with workspace_lock:
            job = get_job(job_id)
            state = pipeline.state(job)
            if not state['segments']:
                raise HTTPException(409, '尚无可导出的字幕')
            path = export_workspace(state, job, format)
            # Capture this revision before releasing the lock; streaming a mutable
            # shared export path can otherwise serve a later revision.
            types = {'md': 'text/markdown', 'txt': 'text/plain', 'vtt': 'text/vtt', 'json': 'application/json', 'srt': 'application/x-subrip',
                     'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
            return Response(path.read_bytes(), media_type=types[format], headers={
                'Content-Disposition': "attachment; filename*=UTF-8''" + quote(path.name), 'Cache-Control': 'no-store'})

    return router
