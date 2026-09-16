from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import srt

from .schemas import Transcript
from .text_utils import safe_filename


def build_srt(transcript: Transcript, video_title: str, output_dir: Path) -> Path:
    subtitles: list[srt.Subtitle] = []
    for segment in transcript.segments:
        content = "\n".join(line.strip() for line in segment.text.replace("\r", "\n").split("\n") if line.strip())
        if not content:
            continue
        start = max(0.0, float(segment.start))
        end = max(start + 0.05, float(segment.end))
        subtitles.append(
            srt.Subtitle(
                index=len(subtitles) + 1,
                start=timedelta(seconds=start),
                end=timedelta(seconds=end),
                content=content,
            )
        )
    if not subtitles:
        raise ValueError("转写结果中没有可导出的字幕片段")

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_filename(video_title)}_完整字幕_{datetime.now():%Y%m%d}.srt"
    destination = output_dir / filename
    # UTF-8 BOM improves automatic encoding detection in common Windows players.
    content = srt.compose(subtitles, reindex=True, strict=False, eol="\r\n")
    destination.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    parsed = list(srt.parse(destination.read_text(encoding="utf-8-sig")))
    if len(parsed) != len(subtitles):
        raise ValueError("SRT 字幕结构校验失败")
    return destination
