"""Verify the installed public API without displaying credentials or user jobs."""
import argparse
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

import httpx


def verify(root: Path, notes: bool = False):
    key = json.loads((root / 'client-key.json').read_text(encoding='utf-8'))['api_key']
    runtime = json.loads((root / 'service-runtime.json').read_text(encoding='utf-8-sig'))
    expected_upstream = f'http://127.0.0.1:{runtime["port"]}'
    matches = []
    deadline = time.monotonic() + 60
    with httpx.Client(timeout=5, trust_env=False) as local:
        while time.monotonic() < deadline:
            try:
                tunnels = local.get('http://127.0.0.1:4040/api/tunnels').raise_for_status().json()['tunnels']
                matches = [t for t in tunnels if t.get('config', {}).get('addr', '').rstrip('/') == expected_upstream]
                if matches:
                    break
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            time.sleep(2)
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one tunnel to the installed API port')
    base = matches[0]['public_url'].rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError('Tunnel did not return a valid HTTPS endpoint')
    if matches[0].get('config', {}).get('inspect') is not False:
        raise RuntimeError('Disable ngrok request inspection before sending credentials')
    headers = {'Authorization': 'Bearer ' + key}
    job_id = None
    with httpx.Client(base_url=base, timeout=45, follow_redirects=False) as client:
        def check(response, expected):
            if response.status_code != expected:
                raise RuntimeError(f'{response.request.method} {response.request.url.path}: HTTP {response.status_code}, expected {expected}')
            return response

        deadline = time.monotonic() + 45
        while True:
            try:
                health = client.get('/healthz', timeout=5)
                if health.status_code == 200 and health.json().get('api_version') == 'v1':
                    break
            except (httpx.HTTPError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Public API did not become ready after tunnel startup')
            time.sleep(2)
        check(client.get('/v1/jobs'), 401)
        check(client.get('/v1/jobs', headers={'Authorization': 'Bearer invalid'}), 401)
        check(client.get('/v1/capabilities', headers=headers), 200)
        check(client.get('/api/settings/llm', headers=headers), 404)
        print('PASS: HTTPS, authentication, desktop isolation')
        try:
            uploaded = check(client.post('/v1/jobs', params={'filename': 'api-self-check.srt'},
                headers={**headers, 'Content-Type': 'application/octet-stream'},
                content=b'1\n00:00:00,000 --> 00:00:02,000\nShuying API self-check.\n'), 202)
            job_id = uploaded.json()['id']
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                state = check(client.get(f'/v1/jobs/{job_id}', headers=headers), 200).json()
                if state['status'] == 'completed':
                    break
                if state['status'] in {'failed', 'canceled'}:
                    raise RuntimeError('Self-check task did not complete')
                time.sleep(3)
            else:
                raise RuntimeError('Self-check task timed out')
            if notes:
                check(client.post(f'/v1/jobs/{job_id}/notes', headers=headers, json={'proofread': False}), 202)
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    state = check(client.get(f'/v1/jobs/{job_id}', headers=headers), 200).json()
                    if state['status'] == 'completed':
                        break
                    if state['status'] in {'failed', 'canceled'}:
                        raise RuntimeError('AI notes failed: ' + str(state.get('error_code')))
                    time.sleep(5)
                else:
                    raise RuntimeError('AI notes timed out')
            result = check(client.get(f'/v1/jobs/{job_id}/result', headers=headers), 200).json()
            if notes and not result['blocks']:
                raise RuntimeError('AI notes did not contain any blocks')
            if notes:
                print('PASS: configured AI generated notes through public API')
            if not result['segments'] or result['segments'][0]['text'] != 'Shuying API self-check.':
                raise RuntimeError('Transcript content did not match the test fixture')
            for fmt in ['md', 'docx', 'txt', 'srt', 'vtt', 'json', 'outline']:
                response = check(client.get(f'/v1/jobs/{job_id}/export', params={'format': fmt}, headers=headers), 200)
                if not response.content:
                    raise RuntimeError(f'Empty {fmt} export')
            print('PASS: upload, processing, transcript, all 7 exports')
            check(client.delete(f'/v1/jobs/{job_id}', headers=headers), 204)
            job_id = None
            print('PASS: test material deleted')
            print('API_URL=' + base)
        finally:
            if job_id:
                # Only clean up the synthetic job created in this invocation.
                try:
                    client.post(f'/v1/jobs/{job_id}/cancel', headers=headers)
                    response = client.delete(f'/v1/jobs/{job_id}', headers=headers)
                    if response.status_code != 204:
                        print('NOTE: self-check material retained; remove after cancellation completes')
                except httpx.HTTPError:
                    print('NOTE: self-check cleanup unavailable')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', type=Path, default=Path(os.environ['LOCALAPPDATA']) / 'ShuyingService')
    parser.add_argument('--notes', action='store_true', help='Also generate a short note using the configured model (may incur provider usage)')
    args = parser.parse_args()
    try:
        verify(args.install_dir, notes=args.notes)
    except Exception as exc:
        # No response bodies, headers, keys, or private task contents are printed.
        print('FAIL: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__))
        raise SystemExit(1)
