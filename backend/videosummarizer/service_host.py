"""Headless single-worker server; public HTTPS is provided by a separate tunnel."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import secrets
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .checkpoints import atomic_json
from .config import Settings
from .service_api import KeyStore, create_service


def main():
    parser = argparse.ArgumentParser(description='Shuying API host and local key administration')
    parser.add_argument('command', choices=['serve', 'create-key', 'revoke-key'])
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--key-id', help='Existing client id to rotate or revoke')
    parser.add_argument('--output', type=Path, help='Private output file for the newly generated client token')
    parser.add_argument('--origin', action='append', default=[], help='Explicit browser CORS origin')
    args = parser.parse_args()
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    keys_file = directory / 'api-keys.json'
    if args.command != 'serve':
        records = json.loads(keys_file.read_text(encoding='utf-8')) if keys_file.exists() else {'keys': []}
        if args.command == 'revoke-key':
            if not args.key_id or not any(k['id'] == args.key_id for k in records['keys']):
                parser.error('Existing --key-id is required')
            for key in records['keys']:
                if key['id'] == args.key_id:
                    key['revoked'] = True
            atomic_json(keys_file, records)
            print('API key revoked')
            return
        if not args.output:
            parser.error('--output is required; tokens are never printed')
        if args.output.resolve() == keys_file:
            parser.error('Token output must not overwrite the key registry')
        if args.output.exists():
            parser.error('Token output already exists; select a new private file')
        key_id = args.key_id or uuid.uuid4().hex
        if args.key_id and not any(k['id'] == key_id for k in records['keys']):
            parser.error('Unknown key id')
        token = secrets.token_urlsafe(48)
        records['keys'] = [k for k in records['keys'] if k['id'] != key_id]
        records['keys'].append({'id': key_id, 'sha256': hashlib.sha256(token.encode()).hexdigest()})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # This file is deliberately outside the repo; installer restricts its directory ACL.
        with args.output.open('x', encoding='utf-8') as output:
            json.dump({'key_id': key_id, 'api_key': token}, output, indent=2)
        atomic_json(keys_file, records)
        print('Client key saved to the specified private output file')
        return

    if not keys_file.is_file():
        parser.error('Create a client key before starting the server')
    # Prevent concurrent workers from processing one database, even on different ports.
    lock = (directory / 'service.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    if os.name == 'nt':
        import msvcrt
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            parser.error('A service already owns this data directory')
    config = Settings(data_dir=directory, port=args.port, max_download_bytes=64 * 1024**2,
                      max_duration_seconds=30 * 60)
    handler = RotatingFileHandler(directory / 'api-service.log', maxBytes=2 * 1024**2, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    import uvicorn
    app = create_service(config, KeyStore(keys_file), allowed_origins=tuple(args.origin))
    uvicorn.run(app, host='127.0.0.1', port=args.port, workers=1, access_log=False,
                proxy_headers=False, limit_concurrency=32, timeout_keep_alive=5,
                log_config=None, timeout_graceful_shutdown=15)


if __name__ == '__main__':
    main()
