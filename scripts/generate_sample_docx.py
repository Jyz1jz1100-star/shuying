from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "tests"))
from test_docx_builder import sample_summary
from videosummarizer.docx_builder import build_docx

if __name__ == "__main__":
    print(build_docx(sample_summary(), ROOT / "qa_output"))
