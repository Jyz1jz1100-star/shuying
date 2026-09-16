"""User-session supervisor for the API and optional preconfigured HTTPS tunnel."""
import json
import logging
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def main():
    config_path = Path(sys.argv[1]).resolve()
    root = config_path.parent
    lock = (root/'supervisor.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    import msvcrt
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return
    handler = RotatingFileHandler(root/'supervisor.log', maxBytes=1024**2, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(message)s')
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root/'app'/'backend')
    env['PYTHONUTF8'] = '1'
    children = {}
    next_start = {}
    try:
        while not (root/'STOP').exists():
            commands = {'api': [config['python'], '-m', 'videosummarizer.service_host', 'serve',
                               '--data-dir', str(root/'data'), '--port', str(config['port'])]}
            for origin in config.get('origins', []):
                commands['api'].extend(['--origin', origin])
            tunnel = root/'ngrok.yml'
            agent = root/'tools'/'ngrok.exe'
            if tunnel.exists() and agent.exists():
                commands['tunnel'] = [str(agent), 'http', f'http://127.0.0.1:{config["port"]}',
                                      '--inspect=false', '--config', str(tunnel), '--log', 'stdout', '--log-format', 'json']
            for name, command in commands.items():
                child = children.get(name)
                if child and child.poll() is None:
                    continue
                if child:
                    logging.warning('%s exited with code %s; restarting after delay', name, child.returncode)
                    children.pop(name)
                    next_start[name] = time.monotonic()+10
                if time.monotonic() < next_start.get(name, 0):
                    continue
                children[name] = subprocess.Popen(command, cwd=root/'app', env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                logging.info('Started %s pid=%s', name, children[name].pid)
            time.sleep(3)
    finally:
        for name, child in children.items():
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
        logging.info('Supervisor stopped')


if __name__ == '__main__':
    main()
