from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from videosummarizer.config import settings
from videosummarizer.whispercpp import WhisperCppTranscriber, _convert_to_wav, _write_wav_chunk


qa_dir = ROOT / "qa_output" / "gpu-whisper"
source = next(qa_dir.glob("source.*"))
full_wav = qa_dir / "full.wav"
sample_wav = qa_dir / "sample-75s.wav"
_convert_to_wav(source, full_wav)
_write_wav_chunk(full_wav, sample_wav, 0, 75)

last_progress = -1


def report(progress: int, message: str) -> None:
    global last_progress
    if progress != last_progress:
        print(f"{progress:02d}% {message}", flush=True)
        last_progress = progress


transcript = WhisperCppTranscriber(settings).transcribe(
    sample_wav,
    "balanced",
    report,
    lambda: None,
    qa_dir,
)
(qa_dir / "transcript.json").write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
print(f"TRANSCRIPT_OK language={transcript.language} segments={len(transcript.segments)}", flush=True)
for segment in transcript.segments[:5]:
    print(f"[{segment.start:.2f}-{segment.end:.2f}] {segment.text}", flush=True)
