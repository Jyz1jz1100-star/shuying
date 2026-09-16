"""Install an operator's encrypted LLM settings without exposing the secret."""
import argparse
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from videosummarizer.config import Settings
from videosummarizer.llm_settings import LLMSettingsStore
from videosummarizer.summarizer import OllamaSummarizer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings-file', type=Path, required=True, help='DPAPI-encrypted settings prepared for this Windows user')
    parser.add_argument('--install-dir', type=Path, default=Path(os.environ['LOCALAPPDATA']) / 'ShuyingService')
    args = parser.parse_args()
    if not (args.install_dir / 'service-runtime.json').is_file():
        raise RuntimeError('Service installation is not visible in this Windows session')
    config = Settings()
    source = LLMSettingsStore(args.settings_file, config.ollama_model)
    provider = source.public()['default_provider']
    if provider != 'openai_compatible':
        raise RuntimeError('The prepared settings must select an online model')
    runtime = source.runtime(provider)
    targets = [args.install_dir / 'data' / 'llm_settings.json', config.llm_settings_path]
    for target in targets:
        db = target.parent / 'jobs.sqlite3'
        if db.is_file():
            with sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True) as connection:
                count = connection.execute('SELECT count(*) FROM jobs WHERE status NOT IN (?,?,?)', ('completed','failed','canceled')).fetchone()[0]
                if count:
                    raise RuntimeError('Wait for active jobs to finish before changing model settings')
    OllamaSummarizer(config, runtime).test_connection()
    for target in targets:
        store = LLMSettingsStore(target, config.ollama_model)
        store.save(provider, runtime.base_url, runtime.model, runtime.api_key)
    print('PASS: online model tested; encrypted settings saved for API service and desktop')
    print('Model: ' + runtime.model)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FAIL: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__))
        raise SystemExit(1)
