"""Reviewable, source-linked evidence workspace for the video summarizer.

Every helper is a pure function over plain dictionaries so a workspace can be
serialized to JSON, stored next to a job and unit tested without FastAPI or
Pydantic. Only the standard library is used; comments are English while user
facing strings stay Chinese.

Terminology:
    original    immutable transcript text produced by the transcription step
    text        current segment text, equal to ``original`` until an edit
    suggested   proofreading suggestion, present only when it changes the text
    review      ``pending`` while a decision is missing, ``accepted`` once a
                segment is finalized, ``unverified`` for uncited paragraphs
    flags       risk markers describing how ``text`` differs from ``original``
"""

from __future__ import annotations

import copy
import html
import math
import re
from collections import Counter
from urllib.parse import parse_qs, urlparse

MAX_SEGMENT_TEXT = 3000
MAX_PARAGRAPH_CHARS = 4000
MAX_QUOTE_CHARS = 600
MAX_BLOCK_SEGMENTS = 80
MAX_BLOCK_CHARS = 12000
MAX_BLOCK_SECONDS = 900.0

REVIEW_PENDING = "pending"
REVIEW_ACCEPTED = "accepted"
REVIEW_UNVERIFIED = "unverified"

FLAG_DIGITS = "digits"
FLAG_NEGATION = "negation"
FLAG_TECHNICAL = "technical"

DIGIT_RE = re.compile(r"\d+(?:[.,]\d+)?")
WORD_RE = re.compile(r"[0-9A-Za-z_'’\-]+")
TECHNICAL_RE = re.compile(
    r"^(?:"
    r"[A-Z]{2,}\d*"                # acronyms such as GPU, LLM2
    r"|[A-Za-z]+\d+"               # word plus digits such as h264, mp3
    r"|\d+[A-Za-z]+"               # digits plus word such as 3d, 7zip
    r"|[a-z]+[A-Z][A-Za-z0-9]*"    # camelCase identifiers
    r"|[0-9A-Za-z]+_[0-9A-Za-z]+"  # snake_case identifiers
    r")$"
)
VIDEO_ID_RE = re.compile(r"^[0-9A-Za-z_-]{6,64}$")
BILIBILI_ID_RE = re.compile(r"/(BV[0-9A-Za-z]{10}|av[0-9]{1,12})(?:/|$)")
SAFE_PLATFORM_DOMAINS = ("youtube.com", "youtu.be", "bilibili.com")
BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

NEGATION_MARKERS = (
    "not", "no", "never", "none", "cannot", "can't", "don't", "doesn't",
    "didn't", "isn't", "aren't", "wasn't", "weren't", "won't", "wouldn't",
    "shouldn't", "couldn't", "without", "nor", "neither",
    "不", "没", "无", "非", "未", "别", "莫", "勿", "禁",
)


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _plain_text(value) -> str:
    """Collapse whitespace so stored text is a single reviewable line."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _escape_inline(value) -> str:
    """Escape user supplied text so it can not inject HTML or markdown blocks."""
    escaped = html.escape(_plain_text(value), quote=False)
    return re.sub(r'([\\`*{}\[\]()!_])', r'\\\1', escaped)


def _to_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, number)


def format_timecode(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _is_technical_token(token: str) -> bool:
    return bool(TECHNICAL_RE.match(token))


def _negation_counts(text: str) -> Counter:
    """Count negation markers so an added or dropped negation can be flagged."""
    lowered = text.lower()
    counts: Counter = Counter()
    for marker in NEGATION_MARKERS:
        if marker.isascii():
            found = len(re.findall(rf"\b{re.escape(marker)}\b", lowered))
        else:
            found = lowered.count(marker)
        if found:
            counts[marker] = found
    return counts


def _technical_counts(text: str) -> Counter:
    return Counter(token for token in WORD_RE.findall(text) if _is_technical_token(token))


def segment_flags(original: str, revised: str) -> list[str]:
    """Return risk flags describing how ``revised`` differs from ``original``."""
    if original == revised:
        return []
    flags: list[str] = []
    if Counter(DIGIT_RE.findall(original)) != Counter(DIGIT_RE.findall(revised)):
        flags.append(FLAG_DIGITS)
    if _negation_counts(original) != _negation_counts(revised):
        flags.append(FLAG_NEGATION)
    if _technical_counts(original) != _technical_counts(revised):
        flags.append(FLAG_TECHNICAL)
    return flags


def make_workspace(transcript: dict, raw: dict | None = None) -> dict:
    """Build the initial workspace from a transcript and optional proofreading.

    ``transcript`` and ``raw`` segments are aligned by position; a raw segment
    only counts as a correction when its text really differs from the transcript
    text. The ``original`` field stays immutable afterwards.
    """
    transcript_segments = _as_list(transcript.get("segments")) if isinstance(transcript, dict) else []
    raw_segments = _as_list(raw.get("segments")) if isinstance(raw, dict) else []
    segments: list[dict] = []
    for position, item in enumerate(transcript_segments):
        if not isinstance(item, dict):
            continue
        start = _to_float(item.get("start"), 0.0)
        end = max(start, _to_float(item.get("end"), start))
        current = _plain_text(item.get("text"))
        original = current
        corrected = ""
        if position < len(raw_segments) and isinstance(raw_segments[position], dict):
            candidate = _plain_text(raw_segments[position].get("text"))
            if candidate:
                original = candidate
                if current != original:
                    corrected = current
        suggested: str | None = None
        if corrected:
            text = corrected
            suggested = corrected
            review = REVIEW_PENDING
            flags = segment_flags(original, corrected)
        else:
            text = original
            review = REVIEW_ACCEPTED
            flags = []
        segments.append(
            {
                "id": f"s{position + 1:06d}",
                "start": start,
                "end": end,
                "original": original,
                "text": text,
                "suggested": suggested,
                "review": review,
                "flags": flags,
            }
        )
    return {"revision": 1, "glossary": [], "blocks": [], "segments": segments}


def apply_edit(state: dict, segment_id: str, text: str | None = None, decision: str | None = None) -> dict:
    """Return a deep copy of ``state`` with one segment decision applied.

    ``decision`` accepts or rejects a proofreading suggestion; passing ``text``
    (optionally with ``decision="custom"``) stores a manual edit of at most
    ``MAX_SEGMENT_TEXT`` characters. Accepting and rejecting both finalize the
    segment: a rejection always restores the immutable ``original`` text. Every
    successful edit bumps the revision and flags referencing blocks as stale.
    """
    if not isinstance(state, dict):
        raise ValueError("state must be a dict")
    result = copy.deepcopy(state)
    segments = result.get("segments")
    if not isinstance(segments, list):
        raise ValueError("state must contain a segments list")
    target = next(
        (item for item in segments if isinstance(item, dict) and item.get("id") == segment_id),
        None,
    )
    if target is None:
        raise ValueError(f"unknown segment id: {segment_id}")

    normalized = decision.strip().lower() if isinstance(decision, str) else None
    if normalized in ("accept", "accepted"):
        new_text = _plain_text(text) if text is not None else str(target.get("text") or target.get("original") or "")
    elif normalized in ("reject", "rejected"):
        new_text = str(target.get("original") or "")
    elif normalized in (None, "", "custom", "edit", "manual"):
        if text is None:
            raise ValueError("custom edit requires text")
        new_text = _plain_text(text)
        if not new_text:
            raise ValueError("edited text must not be empty")
        if len(new_text) > MAX_SEGMENT_TEXT:
            raise ValueError(f"edited text must not exceed {MAX_SEGMENT_TEXT} characters")
    else:
        raise ValueError(f"unknown decision: {decision}")

    if not new_text.strip() or len(new_text) > MAX_SEGMENT_TEXT:
        raise ValueError('字幕必须为 1–3000 字符')
    target["text"] = new_text
    target["review"] = REVIEW_ACCEPTED
    target["flags"] = segment_flags(str(target.get("original") or ""), new_text)
    result["revision"] = int(result.get("revision") or 0) + 1
    for block in _as_list(result.get("blocks")):
        if isinstance(block, dict) and segment_id in _as_list(block.get("segment_ids")):
            block["stale"] = True
    return result


def split_blocks(segments: list[dict]) -> list[list[str]]:
    """Split segments into stable chunks of at most 80 items, 12000 chars, 900s.

    Only ``id``, ``start``, ``end`` and ``original`` are read, so the same input
    always yields the same boundaries regardless of later edits.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    characters = 0
    start = 0.0
    for item in _as_list(segments):
        if not isinstance(item, dict):
            continue
        segment_id = item.get("id")
        if not isinstance(segment_id, str) or not segment_id:
            continue
        segment_start = _to_float(item.get("start"), 0.0)
        segment_end = max(segment_start, _to_float(item.get("end"), segment_start))
        characters_in_item = len(str(item.get("original") or ""))
        if not current:
            start = segment_start
        if current and (
            len(current) >= MAX_BLOCK_SEGMENTS
            or characters + characters_in_item > MAX_BLOCK_CHARS
            or (segment_end - start) > MAX_BLOCK_SECONDS
        ):
            blocks.append(current)
            current = []
            characters = 0
            start = segment_start
        current.append(segment_id)
        characters += characters_in_item
    if current:
        blocks.append(current)
    return blocks


def normalize_block(payload: dict, allowed_segments: list[dict], block_id: str) -> dict:
    """Normalize a model produced chapter against the segments it may cite.

    Unknown citation ids are dropped; a paragraph that keeps no valid id is
    marked ``unverified`` so the reviewer sees the gap. Paragraph text is
    clipped to ``MAX_PARAGRAPH_CHARS``.
    """
    allowed_ids = [
        item["id"]
        for item in _as_list(allowed_segments)
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    ]
    allowed = set(allowed_ids)
    source = payload if isinstance(payload, dict) else {}
    heading = _plain_text(source.get("heading"))[:160] or f"章节 {block_id}"
    paragraphs: list[dict] = []
    for item in _as_list(source.get("paragraphs")):
        if not isinstance(item, dict):
            continue
        text = _plain_text(item.get("text"))
        if not text:
            continue
        # Keep the whole validated paragraph; never silently discard evidence.
        cited: list[str] = []
        for segment_id in _as_list(item.get("segment_ids")):
            if isinstance(segment_id, str) and segment_id in allowed and segment_id not in cited:
                cited.append(segment_id)
        paragraphs.append(
            {
                "text": text,
                "segment_ids": cited,
                "review": REVIEW_PENDING if cited else REVIEW_UNVERIFIED,
            }
        )
    return {
        "id": block_id,
        "heading": heading,
        "paragraphs": paragraphs,
        "segment_ids": allowed_ids,
        "stale": False,
    }


def _host_matches(host: str, domains) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _youtube_video_id(parsed, host: str) -> str:
    if host == "youtu.be" or host.endswith(".youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
    else:
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        if not candidate:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
                candidate = parts[1]
    return candidate if VIDEO_ID_RE.match(candidate) else ""


def _bilibili_video_id(path: str) -> str:
    match = BILIBILI_ID_RE.search(path or "")
    return match.group(1) if match else ""


def _time_link(source_url: str, seconds: float) -> str:
    """Return a timestamped link for known platforms, else an empty string.

    Links are rebuilt from a validated video id, so extra query parameters,
    HTML fragments or non ``https``/localhost sources never reach the output.
    """
    try:
        parsed = urlparse(str(source_url or "").strip())
    except ValueError:
        return ''
    if parsed.username or parsed.password:
        return ''
    if parsed.scheme.lower() != "https":
        return ""
    host = (parsed.hostname or "").lower()
    if not host or host in BLOCKED_HOSTS or "." not in host:
        return ""
    if not _host_matches(host, SAFE_PLATFORM_DOMAINS):
        return ""
    position = max(0, int(seconds))
    if _host_matches(host, ("youtube.com", "youtu.be")):
        video_id = _youtube_video_id(parsed, host)
        if not video_id:
            return ""
        return f"https://www.youtube.com/watch?v={video_id}&t={position}s"
    video_id = _bilibili_video_id(parsed.path)
    if not video_id:
        return ""
    return f"https://www.bilibili.com/video/{video_id}?t={position}"


def citation(segment_ids: list[str], segments: list[dict], source_url: str = "") -> dict:
    """Build a source citation from valid ids, ignoring everything unknown."""
    index = {
        item["id"]: item
        for item in _as_list(segments)
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    }
    ordered: list[dict] = []
    seen: set[str] = set()
    for segment_id in _as_list(segment_ids):
        if not isinstance(segment_id, str) or segment_id in seen:
            continue
        item = index.get(segment_id)
        if item is None:
            continue
        seen.add(segment_id)
        ordered.append(item)
    if not ordered:
        return {"start": 0.0, "end": 0.0, "quote": "", "url": ""}
    start = min(_to_float(item.get("start"), 0.0) for item in ordered)
    end = max(max(start, _to_float(item.get("end"), start)) for item in ordered)
    quote = _plain_text(" ".join(str(item.get("text") or item.get("original") or "") for item in ordered))
    return {
        "start": start,
        "end": end,
        "quote": quote[:MAX_QUOTE_CHARS],
        "url": _time_link(source_url, start),
    }


def render_markdown(state: dict, title: str, source_url: str = "") -> str:
    """Render the workspace as review friendly markdown without raw HTML."""
    source = state if isinstance(state, dict) else {}
    segments = [item for item in _as_list(source.get("segments")) if isinstance(item, dict)]
    blocks = [item for item in _as_list(source.get("blocks")) if isinstance(item, dict)]
    lines: list[str] = [f"# {_escape_inline(title) or '未命名总结'}", ""]

    labels: list[str] = ['讲义草稿：引用提供原文定位，不代表事实已核实']
    if source_url and source_url.startswith('https://'):
        lines.extend(['来源：' + _escape_inline(source_url), ''])
    if any(item.get("review") == REVIEW_PENDING for item in segments):
        labels.append("草稿：仍存在待人工确认的片段")
    if any(item.get("stale") for item in blocks):
        labels.append("待更新：部分章节引用了已修改的片段")
    for label in labels:
        lines.append(f"> {label}")
    if labels:
        lines.append("")

    glossary: list[str] = []
    for item in _as_list(source.get("glossary")):
        if isinstance(item, str):
            glossary.append('- ' + _escape_inline(item))
            continue
        if not isinstance(item, dict):
            continue
        term = _escape_inline(item.get("term"))
        definition = _escape_inline(item.get("definition"))
        if term and definition:
            glossary.append(f"- **{term}**：{definition}")
    if glossary:
        lines.append("## 术语表")
        lines.extend(glossary)
        lines.append("")

    for block in blocks:
        heading = _escape_inline(block.get("heading")) or "未命名章节"
        suffix = "（待更新）" if block.get("stale") else ""
        lines.append(f"## {heading}{suffix}")
        lines.append("")
        for paragraph in _as_list(block.get("paragraphs")):
            if not isinstance(paragraph, dict):
                continue
            body = _escape_inline(paragraph.get("text"))
            if not body:
                continue
            if paragraph.get("review") == REVIEW_UNVERIFIED:
                body = f"{body}（未核实）"
            lines.append(body)
            lines.append("")
            cite = citation(_as_list(paragraph.get("segment_ids")), segments, source_url)
            if not cite["quote"]:
                continue
            quote = _escape_inline(cite["quote"])[:MAX_QUOTE_CHARS]
            stamp = format_timecode(cite["start"])
            if cite["url"]:
                lines.append(f"> [{stamp}]({cite['url']}) 原文：“{quote}”")
            else:
                lines.append(f"> [{stamp}] 原文：“{quote}”")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
