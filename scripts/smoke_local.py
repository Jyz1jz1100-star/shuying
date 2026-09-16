"""Run an opt-in real Ollama smoke test using the authored demonstration SRT."""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from videosummarizer.config import Settings
from videosummarizer.database import Database
from videosummarizer.learning import LearningPipeline
from videosummarizer.llm_settings import LLMSettingsStore

parser=argparse.ArgumentParser()
parser.add_argument('--model',required=True,help='An already downloaded Ollama model')
parser.add_argument('--data-dir',required=True,type=Path,help='An empty disposable test directory')
args=parser.parse_args()
if args.data_dir.exists() and any(args.data_dir.iterdir()):
    parser.error('data-dir must be empty')
config=Settings(data_dir=args.data_dir.resolve(),ollama_model=args.model)
config.ensure_directories()
db=Database(config.db_path); db.initialize()
directory=config.jobs_dir/'demo'; directory.mkdir()
shutil.copyfile(Path(__file__).resolve().parents[1]/'examples/checkpoints.srt',directory/'input.srt')
db.create_job('demo','',directory)
db.update_job('demo',input_type='srt',title='检查点与可信讲义 示例')
pipeline=LearningPipeline(config,db,LLMSettingsStore(config.llm_settings_path,args.model))
started=time.monotonic()
path=pipeline.run('demo')
state=pipeline.state(db.get_job('demo'))
print(json.dumps({'model':args.model,'seconds':round(time.monotonic()-started,2),
 'blocks':len(state['blocks']),'paragraphs':sum(len(b['paragraphs']) for b in state['blocks']),
 'uncited':sum(not p['segment_ids'] for b in state['blocks'] for p in b['paragraphs']),
 'docx':str(path)},ensure_ascii=True))
