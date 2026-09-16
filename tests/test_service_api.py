import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videosummarizer.config import Settings
from videosummarizer.service_api import create_service, KeyStore

TOKEN = 'a' * 48
OTHER = 'b' * 48
SRT = '1\n00:00:01,000 --> 00:00:03,000\nAPI example text\n'.encode()


@pytest.fixture
def service(tmp_path):
    config = Settings(data_dir=tmp_path, max_download_bytes=1024, max_duration_seconds=60)
    registry = tmp_path / 'keys.json'
    registry.write_text(json.dumps({'keys': [{'id': name, 'sha256': hashlib.sha256(token.encode()).hexdigest()} for name, token in [('a', TOKEN), ('b', OTHER)]]}))
    app = create_service(config, KeyStore(registry), start_worker=False)
    return app, TestClient(app), registry


def headers(token=TOKEN):
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/octet-stream'}


def upload(client):
    response = client.post('/v1/jobs?filename=example.srt', headers=headers(), content=SRT)
    assert response.status_code == 202, response.text
    return response.json()['id']


def test_phone_summary_map_and_transcript_are_separate(service, monkeypatch):
    from videosummarizer.reading_products import SummarySection, MapSection
    app, client, _ = service
    calls = []

    class Writer:
        def __init__(self, *args): pass
        def ensure_model(self, *args): pass
        def unload_model(self): pass
        def _chat_model(self, schema, prompt):
            calls.append(schema)
            sid = json.loads(prompt.split('\n字幕：')[1])[0]['id']
            if schema is SummarySection:
                return schema(heading='要点', takeaway='核心结论', points=[{'text': '精简重点', 'segment_ids': [sid]}])
            assert schema is MapSection
            return schema(topic='主题', branches=[{'label': '方法', 'children': [{'label': '关键词', 'segment_ids': [sid]}]}])

    monkeypatch.setattr('videosummarizer.learning.OllamaSummarizer', Writer)
    response = client.post('/v1/jobs?filename=example.srt&mode=lecture', headers=headers(), content=SRT)
    job_id = response.json()['id']
    app.state.pipeline.run(job_id)
    result = client.get(f'/v1/jobs/{job_id}/result', headers=headers()).json()
    assert result['segments'][0]['text'] == 'API example text'
    assert result['summary'][0]['takeaway'] == '核心结论'
    assert result['mindmap'][0]['branches'][0]['children'][0]['label'] == '关键词'
    assert calls == [SummarySection, MapSection]
    outline = client.get(f'/v1/jobs/{job_id}/export?format=outline', headers=headers()).text
    assert '关键词' in outline and 'API example text' not in outline


def test_auth_and_no_desktop_exposure(service):
    app, client, registry = service
    assert client.get('/healthz').status_code == 200
    assert client.get('/v1/jobs').status_code == 401
    assert client.get('/v1/jobs?api_key='+TOKEN).status_code == 401
    assert client.get('/v1/jobs', headers=headers('wrong')).status_code == 401
    for path in ['/api/settings/llm', '/api/live/devices', '/api/shutdown', '/api/jobs']:
        assert client.get(path, headers=headers()).status_code == 404
    schema = client.get('/openapi.json').json()
    assert schema['paths']['/v1/jobs']['post']['security']
    assert 'application/octet-stream' in schema['paths']['/v1/jobs']['post']['requestBody']['content']
    assert client.get('/v1/capabilities', headers=headers()).json()['url_import'] is True
    registry.write_text('{"keys": []}')
    assert client.get('/v1/jobs', headers=headers()).status_code == 401


def test_mobile_page_is_public_but_data_remains_protected(service):
    _, client, _ = service
    page = client.get('/')
    assert page.status_code == 200
    assert 'name="viewport"' in page.text and '/mobile.js' in page.text
    assert 'frame-ancestors' in page.headers['content-security-policy']
    assert page.headers['cache-control'] == 'no-store'
    assert TOKEN not in page.text
    script = client.get('/mobile.js')
    assert script.status_code == 200
    assert 'application/javascript' in script.headers['content-type']
    assert TOKEN not in script.text
    assert client.get('/v1/jobs').status_code == 401
    assert '/' not in client.get('/openapi.json').json()['paths']


def test_media_probe_rejects_playlist_and_accepts_wav(tmp_path):
    import wave
    from fastapi import HTTPException
    from videosummarizer.materials import inspect_material
    config = Settings(data_dir=tmp_path, max_duration_seconds=60)
    media = tmp_path / 'sample.wav'
    with wave.open(str(media), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b'\0\0' * 16000)
    duration, digest = inspect_material(media, False, config)
    assert duration == pytest.approx(1) and len(digest) == 64
    media.write_text('#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1/private.ts\n#EXT-X-ENDLIST\n')
    with pytest.raises(Exception):
        inspect_material(media, False, config)


def test_job_storage_cannot_escape_service_directory(service, tmp_path):
    app, client, _ = service
    job_id = upload(client)
    protected = tmp_path / 'outside'
    protected.mkdir()
    (protected / 'keep.txt').write_text('keep')
    with app.state.database.connect() as connection:
        connection.execute('UPDATE jobs SET job_dir=?,status=? WHERE id=?', (str(protected), 'completed', job_id))
    assert client.delete('/v1/jobs/'+job_id, headers=headers()).status_code == 500
    assert (protected / 'keep.txt').read_text() == 'keep'


def test_ownership_on_every_job_operation(service):
    app, client, _ = service
    job_id = upload(client)
    assert 'job_dir' not in client.get('/v1/jobs/'+job_id, headers=headers()).json()
    assert client.get('/v1/jobs', headers=headers(OTHER)).json()['total'] == 0
    for method, suffix in [('get',''),('get','/result'),('get','/export'),('post','/cancel'),('post','/retry'),('post','/notes'),('delete','')]:
        response = getattr(client, method)('/v1/jobs/'+job_id+suffix, headers={**headers(OTHER), 'Content-Type': 'application/json'}, **({'json': {}} if suffix == '/notes' else {}))
        assert response.status_code == 404, (method,suffix,response.text)


def test_complete_export_delete_and_pagination(service):
    app, client, _ = service
    job_id = upload(client)
    assert client.get(f'/v1/jobs/{job_id}/result', headers=headers()).status_code == 409
    app.state.pipeline.run(job_id)
    result = client.get(f'/v1/jobs/{job_id}/result', headers=headers())
    assert result.status_code == 200 and result.json()['segments'][0]['text'] == 'API example text'
    assert 'job_dir' not in result.text
    for fmt in ['md','docx','srt','vtt','txt','json','outline']:
        response = client.get(f'/v1/jobs/{job_id}/export?format={fmt}', headers=headers())
        assert response.status_code == 200 and response.content
    assert client.get('/v1/jobs?limit=1&offset=1', headers=headers()).json()['items'] == []
    assert client.post(f'/v1/jobs/{job_id}/retry', headers=headers()).status_code == 409
    assert client.delete(f'/v1/jobs/{job_id}', headers=headers()).status_code == 204
    assert client.get('/v1/jobs', headers=headers()).json()['total'] == 0
    assert client.get(f'/v1/jobs/{job_id}', headers=headers()).status_code == 404


def test_upload_limits_and_validation(service):
    app, client, _ = service
    for name in ['../test.srt','a/b.srt','C:test.srt']:
        assert client.post('/v1/jobs', params={'filename': name}, headers=headers(), content=SRT).status_code == 400
    assert client.post('/v1/jobs?filename=a.srt', headers=headers(), content=b'x'*1025).status_code == 413
    assert client.post('/v1/jobs?filename=a.srt', headers=headers(), content=iter([b'x'*800,b'x'*800])).status_code == 413
    assert client.post('/v1/jobs?filename=a.exe', headers=headers(), content=b'MZ').status_code == 400
    assert client.post('/v1/jobs?filename=a.srt', headers=headers(), content=b'bad').status_code == 400
    assert client.post('/v1/jobs?filename=a.srt', headers={'Authorization': 'Bearer '+TOKEN}, content=SRT).status_code == 415
    assert client.get('/v1/jobs?limit=-1', headers=headers()).status_code == 422
    assert app.state.database.list_jobs() == []
    assert list((Path(app.state.database.path).parent/'jobs').iterdir()) == []


def test_capacity_and_active_delete(service):
    app, client, _ = service
    ids = [upload(client) for _ in range(4)]
    assert client.post('/v1/jobs?filename=a.srt', headers=headers(), content=SRT).status_code == 429
    assert client.delete('/v1/jobs/'+ids[0], headers=headers()).status_code == 409
    app.state.database.update_job(ids[0], status='failed')
    app.state.manager.active_job_id = ids[0]
    assert client.post('/v1/jobs/'+ids[0]+'/retry', headers=headers()).status_code == 409
    assert client.delete('/v1/jobs/'+ids[0], headers=headers()).status_code == 409


def test_rate_limit_and_cors(tmp_path):
    registry = tmp_path/'keys.json'
    registry.write_text(json.dumps({'keys':[{'id':'a','sha256':hashlib.sha256(TOKEN.encode()).hexdigest()}]}))
    app = create_service(Settings(data_dir=tmp_path),KeyStore(registry), start_worker=False,
                         allowed_origins=('https://client.example',), requests_per_minute=2)
    client = TestClient(app)
    for _ in range(2):
        assert client.get('/v1/jobs',headers=headers()).status_code == 200
    assert client.get('/v1/jobs',headers=headers()).status_code == 429
    response = client.options('/v1/jobs',headers={'Origin':'https://client.example','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
    assert response.status_code == 200 and response.headers['access-control-allow-origin'] == 'https://client.example'
    assert client.options('/v1/jobs',headers={'Origin':'https://evil.example','Access-Control-Request-Method':'POST'}).status_code == 400


def test_notes_uses_operator_default_even_for_old_local_job(service, monkeypatch):
    app, client, _ = service
    job_id = upload(client)
    app.state.pipeline.run(job_id)
    assert app.state.database.get_job(job_id)['llm_provider'] == 'local'
    monkeypatch.setattr('videosummarizer.llm_settings._protect_secret', lambda value: 'protected')
    monkeypatch.setattr('videosummarizer.llm_settings._unprotect_secret', lambda value: 'test-secret')
    app.state.pipeline.llm_settings.save('openai_compatible', 'https://example.com/v1', 'test-model', 'test-secret')
    response = client.post(f'/v1/jobs/{job_id}/notes', headers={**headers(), 'Content-Type': 'application/json'}, json={})
    assert response.status_code == 202
    assert app.state.database.get_job(job_id)['llm_provider'] == 'openai_compatible'
    caps = client.get('/v1/capabilities', headers=headers()).json()
    assert caps['notes'] == {'provider': 'openai_compatible', 'model': 'test-model'}
    assert 'test-secret' not in json.dumps(caps)
    response = client.post('/v1/jobs?filename=example.srt&mode=lecture', headers=headers(), content=SRT)
    assert response.status_code == 202
    assert app.state.database.get_job(response.json()['id'])['llm_provider'] == 'openai_compatible'


def test_link_job_is_owned_and_processes_with_existing_pipeline(service, monkeypatch):
    from videosummarizer.schemas import Transcript, TranscriptSegment
    app, client, _ = service
    monkeypatch.setattr('videosummarizer.video_links.validate_public_url', lambda value: value)
    body = {'url': 'https://youtu.be/BaW_jenozKc'}
    assert client.post('/v1/jobs/link', json=body).status_code == 401
    h = {'Authorization': 'Bearer '+TOKEN}
    assert client.post('/v1/jobs/link', json={'url':'http://127.0.0.1'}, headers=h).status_code == 400
    response = client.post('/v1/jobs/link', json=body, headers=h)
    assert response.status_code == 202
    job_id = response.json()['id']
    assert app.state.database.get_job(job_id)['url'] == 'https://www.youtube.com/watch?v=BaW_jenozKc'
    assert client.get('/v1/jobs/'+job_id, headers=headers(OTHER)).status_code == 404
    monkeypatch.setattr(app.state.pipeline, '_probe', lambda *a: {'title':'Test video','duration':10,'extractor':'youtube'})
    monkeypatch.setattr(app.state.pipeline, '_subtitle_transcript', lambda *a: Transcript(language='en',source='human_subtitles',segments=[TranscriptSegment(start=0,end=2,text='Link transcript')]))
    app.state.pipeline.run(job_id)
    assert client.get('/v1/jobs/'+job_id, headers=h).json()['status'] == 'completed'
    assert client.get('/v1/jobs/'+job_id+'/result', headers=h).json()['segments'][0]['text'] == 'Link transcript'
    assert client.delete('/v1/jobs/'+job_id, headers=h).status_code == 204


def test_gpu_default_and_explicit_cpu_for_both_inputs(service, monkeypatch):
    app, client, _ = service
    monkeypatch.setattr('videosummarizer.video_links.validate_public_url', lambda value: value)
    for device in (None, 'cpu'):
        params = {'filename': 'test.srt'}
        body = {'url': 'https://youtu.be/BaW_jenozKc'}
        if device:
            params['device'] = device
            body['device'] = device
        responses = [client.post('/v1/jobs', params=params, content=SRT, headers=headers()),
                     client.post('/v1/jobs/link', json=body, headers={'Authorization': 'Bearer '+TOKEN})]
        for response in responses:
            assert response.status_code == 202
            assert app.state.database.get_job(response.json()['id'])['transcription_device'] == (device or 'gpu')
            assert app.state.database.get_job(response.json()['id'])['transcription_profile'] == 'accurate'
