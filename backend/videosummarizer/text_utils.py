from __future__ import annotations

import html
import re
from pathlib import Path

from .schemas import TranscriptSegment


TIMESTAMP_RE = re.compile(r"^(?P<start>(?:\d+:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*(?P<end>(?:\d+:)?\d{2}:\d{2}[.,]\d{3})(?:\s+[^\r\n]*)?$")
TAG_RE = re.compile(r"<[^>]+>")


def parse_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        hours, minutes, seconds = parts
    if not 0 <= int(minutes) < 60 or not 0 <= float(seconds) < 60 or int(hours) < 0:
        raise ValueError('无效字幕时间戳')
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_subtitle(path: Path) -> list[TranscriptSegment]:
    content = path.read_text(encoding="utf-8-sig", errors="strict").replace("\r\n", "\n").replace('\r', '\n')
    segments: list[TranscriptSegment] = []
    last_start = -1.0
    for block in re.split(r"\n\s*\n", content):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or re.match(r'^(?:WEBVTT|NOTE|STYLE|REGION)(?:\s|$)', lines[0]):
            continue
        timestamp_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timestamp_index is None:
            continue
        match = TIMESTAMP_RE.fullmatch(lines[timestamp_index])
        if not match:
            raise ValueError('无效字幕时间戳')
        if any('-->' in line for line in lines[timestamp_index + 1:]):
            raise ValueError('字幕片段之间需要空行')
        start = parse_timestamp(match.group('start'))
        end = parse_timestamp(match.group('end'))
        if end < start:
            raise ValueError('字幕结束时间不能早于开始时间')
        if start < last_start:
            raise ValueError('字幕开始时间未按顺序排列')
        last_start = start
        text = " ".join(lines[timestamp_index + 1 :])
        text = html.unescape(TAG_RE.sub("", text)).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        segments.append(TranscriptSegment(start=start, end=max(start, end), text=text))
    return segments


def format_timecode(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def transcript_lines(segments: list[TranscriptSegment]) -> str:
    return "\n".join(f"[{format_timecode(item.start)}-{format_timecode(item.end)}] {item.text}" for item in segments)


def chunk_segments(segments: list[TranscriptSegment], max_seconds: int, max_characters: int) -> list[list[TranscriptSegment]]:
    chunks: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    characters = 0
    start = 0.0
    for segment in segments:
        if not current:
            start = segment.start
        would_exceed = current and ((segment.end - start) > max_seconds or characters + len(segment.text) > max_characters)
        if would_exceed:
            chunks.append(current)
            current = []
            characters = 0
            start = segment.start
        current.append(segment)
        characters += len(segment.text)
    if current:
        chunks.append(current)
    return chunks


def safe_filename(value: str, fallback: str = "视频总结") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)[:100]
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if not cleaned or cleaned.upper() in reserved:
        cleaned = fallback
    return cleaned
