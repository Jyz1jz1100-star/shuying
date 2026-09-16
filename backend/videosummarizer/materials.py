from __future__ import annotations

import shutil
import uuid
from pathlib import Path
import av
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from .checkpoints import atomic_json, file_fingerprint
from .security import validate_public_url, UnsafeUrlError
from .text_utils import parse_subtitle


def inspect_material(destination, is_subtitle, settings):
    if is_subtitle:
        destination.read_text(encoding='utf-8-sig', errors='strict')
        segments = parse_subtitle(destination)
        if not segments:
            raise HTTPException(400, '字幕中没有有效时间段')
        if any(s.end < s.start for s in segments) or any(b.start < a.start for a, b in zip(segments, segments[1:])):
            raise HTTPException(400, '字幕时间必须顺序排列')
        duration = max(s.end for s in segments)
    else:
        # Disallow playlists and external protocols disguised as ordinary media.
        with av.open(str(destination), options={'protocol_whitelist': 'file',
                     'format_whitelist': 'mov,matroska,webm,mp3,wav,flac', 'enable_drefs': '0'}) as media:
            if not media.streams.audio:
                raise HTTPException(400, '文件没有可用音轨')
            duration = float(media.duration or 0) / av.time_base
            if duration <= 0:
                stream = media.streams.audio[0]
                duration = float((stream.duration or 0) * (stream.time_base or 0))
    if not 0 < duration <= settings.max_duration_seconds:
        raise HTTPException(400, '材料时长超过当前服务限制或无有效时长')
    return duration, file_fingerprint(destination)


async def import_material(request: Request, filename: str, *, database, manager, settings,
                          llm_provider='local', transcription_profile='balanced', source_url='',
                          processing_mode='transcript', transcription_device='cpu', owner_id=None):
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
    limit = min(10 * 1024**2, settings.max_download_bytes) if is_subtitle else settings.max_download_bytes
    persisted = False
    try:
        size = 0
        with destination.open('wb') as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, '文件超过当前服务的大小限制')
                if shutil.disk_usage(directory).free < len(chunk) + 128 * 1024**2:
                    raise HTTPException(507, '磁盘空间不足')
                output.write(chunk)
        duration, digest = await run_in_threadpool(inspect_material, destination, is_subtitle, settings)
        atomic_json(directory / 'input_metadata.json', {'sha256': digest, 'size': size})
        job = database.create_job(job_id, source_url, directory, transcription_profile, llm_provider, processing_mode, transcription_device, owner_id=owner_id)
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
