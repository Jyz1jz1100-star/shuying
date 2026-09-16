from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from videosummarizer.checkpoints import atomic_json
from videosummarizer.config import Settings
from videosummarizer.database import Database
from videosummarizer.evidence import make_workspace, apply_edit, normalize_block, citation, render_markdown
from videosummarizer.learning import LearningPipeline, CitedBlock
from videosummarizer.manager import JobManager
from videosummarizer.llm_settings import LLMRuntimeSettings
from videosummarizer.schemas import Transcript, TranscriptSegment
from videosummarizer.workspace_api import router_for


def raw_transcript(n=1):
    return {'language':'zh', 'source':'human_subtitles', 'segments':[
        {'start': i*3, 'end':i*3+2, 'text':f'第{i}段：GPU 不需要 32 GB。'} for i in range(n)]}


@pytest.fixture
def project(tmp_path):
    config = Settings(data_dir=tmp_path)
    config.ensure_directories()
    db = Database(config.db_path)
    db.initialize()
    settings = SimpleNamespace(runtime=lambda _: LLMRuntimeSettings('local','fake-model'))
    pipeline = LearningPipeline(config,db,settings)
    manager = JobManager(db,pipeline)
    app = FastAPI()
    app.include_router(router_for(db,pipeline,manager,SimpleNamespace(active=False),config))
    return config,db,pipeline,manager,TestClient(app)


def create(project, n=1):
    config, db, pipeline, manager, client = project
    directory = config.jobs_dir/'test'
    directory.mkdir()
    db.create_job('test','',directory)
    db.update_job('test',status='failed',title='测试讲义')
    atomic_json(directory/'transcript_raw.json',raw_transcript(n))
    return directory


def test_correction_direction_and_rejection():
    original = raw_transcript()
    corrected = raw_transcript()
    corrected['segments'][0]['text'] = 'GPU 需要 64 GB。'
    state = make_workspace(corrected,original)
    s = state['segments'][0]
    assert s['original'] == original['segments'][0]['text']
    assert s['text'] == corrected['segments'][0]['text']
    assert {'digits','negation'} <= set(s['flags'])
    reverted = apply_edit(state,s['id'],None,'reject')
    assert reverted['segments'][0]['text'] == s['original']
    assert state['segments'][0]['text'] != s['original']
    edited = apply_edit(state,s['id'],'人工修订内容','accept')
    assert edited['segments'][0]['text'] == '人工修订内容'


def test_invalid_reference_and_markdown_injection():
    state = make_workspace(raw_transcript())
    block = normalize_block({'heading':'<script>', 'paragraphs':[{'text':'![x](https://evil.test/pixel)', 'segment_ids':['unknown']}]},state['segments'],'b0')
    assert block['paragraphs'][0]['review'] == 'unverified'
    assert not block['paragraphs'][0]['segment_ids']
    state['blocks'] = [block]
    md = render_markdown(state,'<script>')
    assert '<script>' not in md and '![x](' not in md
    for url in ['javascript:alert(1)', 'http://localhost:8765', 'https://youtube.com.evil.test/watch?v=abcdefghijk']:
        assert citation(['s000001'],state['segments'],url)['url'] == ''


def test_import_without_whisper_or_llm(project):
    client = project[-1]
    content = '1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n'
    response = client.post('/api/import?filename=lesson.srt',content=content.encode())
    assert response.status_code == 202
    assert response.json()['input_type'] == 'srt'
    assert client.post('/api/import?filename=bad.srt',content=b'not subtitles').status_code == 400
    assert client.post('/api/import?filename=bad.exe',content=b'MZ').status_code == 400
    invalid = '1\n00:00:05,000 --> 00:00:02,000\n倒序\n'
    assert client.post('/api/import?filename=bad.srt',content=invalid.encode()).status_code == 400


def test_revision_stale_export_and_media(project):
    directory = create(project)
    config,db,pipeline,manager,client=project
    state = make_workspace(raw_transcript())
    state['blocks'] = [normalize_block({'heading':'章节','paragraphs':[{'text':'内容', 'segment_ids':['s000001']}]},state['segments'],'b0000')]
    pipeline.save(db.get_job('test'),state)
    response=client.patch('/api/jobs/test/segments/s000001',json={'revision':1,'text':'人工修订'})
    assert response.status_code==200
    assert response.json()['blocks'][0]['stale'] is True
    assert response.json()['segments'][0]['human_edited'] is True
    assert client.patch('/api/jobs/test/segments/s000001',json={'revision':1,'text':'覆盖'}).status_code==409
    assert (directory/'history/revision-1.json').is_file()
    for format in ['md','json','docx','srt']:
        assert client.get('/api/jobs/test/export',params={'format':format}).status_code==200
    (directory/'input.mp3').write_bytes(b'fake')
    assert client.delete('/api/jobs/test/media').status_code==200
    assert not (directory/'input.mp3').exists()
    assert (directory/'workspace.json').exists()
    assert client.get('/api/jobs/test/media').status_code==404


def test_resume_and_local_regeneration(project, monkeypatch):
    directory=create(project,161)
    config,db,pipeline,manager,client=project
    calls=[]
    fail_once=[True]
    class FakeWriter:
        def __init__(self,*args): pass
        def ensure_model(self,*args): pass
        def unload_model(self): pass
        def _chat_model(self,cls,prompt):
            data=json.loads(prompt.split('\n字幕：',1)[1].split('\n再次核对',1)[0])
            calls.append(data[0]['id'])
            if data[0]['id']=='s000081' and fail_once[0]:
                fail_once[0]=False
                raise RuntimeError('interrupted')
            return CitedBlock(heading='章节',paragraphs=[{'text':'讲义正文','segment_ids':[data[0]['id']]}])
    monkeypatch.setattr('videosummarizer.learning.OllamaSummarizer',FakeWriter)
    with pytest.raises(Exception): pipeline.run('test')
    assert len(pipeline.state(db.get_job('test'))['blocks'])==1
    pipeline.run('test')
    assert calls.count('s000001')==1
    assert db.get_job('test')['status']=='completed'
    state=pipeline.state(db.get_job('test'))
    result=client.patch('/api/jobs/test/segments/s000081',json={'revision':state['revision'],'text':'用户修订'})
    assert result.status_code==200
    previous=len(calls)
    pipeline.run('test')
    assert calls[previous:]==['s000081']
    assert (directory/'transcript_raw.json').exists()


def test_retry_preserves_files(project):
    directory=create(project)
    project[3].retry('test')
    assert (directory/'transcript_raw.json').exists()


def test_clear_media_requires_saved_transcript(project):
    directory = create(project)
    (directory/'input.mp3').write_bytes(b'only source')
    assert project[-1].delete('/api/jobs/test/media').status_code == 409
    assert (directory/'input.mp3').read_bytes() == b'only source'


def test_enqueue_failure_preserves_import(project, monkeypatch):
    def fail(_):
        raise RuntimeError('queue unavailable')
    monkeypatch.setattr(project[3], 'enqueue', fail)
    content = '1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n'
    assert project[-1].post('/api/import?filename=lesson.srt', content=content.encode()).status_code == 400
    files = list(project[0].jobs_dir.glob('*/input.srt'))
    assert len(files) == 1 and files[0].read_text(encoding='utf-8') == content
    assert project[1].get_job(files[0].parent.name)['status'] == 'failed'


def test_legacy_migration_does_not_forge_citations(project):
    directory=create(project)
    atomic_json(directory/'transcript.json',raw_transcript())
    state=project[2].state(project[1].get_job('test'))
    assert state['legacy'] is True and state['blocks']==[]
