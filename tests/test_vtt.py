from pathlib import Path

import pytest

from videosummarizer.text_utils import parse_subtitle


def _write(tmp_path: Path, text: str, suffix: str = ".vtt") -> Path:
    path = tmp_path / f"captions{suffix}"
    path.write_bytes(text.encode("utf-8-sig"))
    return path


def test_webvtt_metadata_tags_entities_and_settings(tmp_path: Path):
    path = _write(
        tmp_path,
        "WEBVTT\nKind: captions\nLanguage: en\n\n"
        "NOTE this is ignored\n\n"
        "STYLE\n::cue { color: yellow }\n\n"
        "REGION\nid:fred\nwidth:40%\n\n"
        "intro\n"
        "00:01.000 --> 00:03.500 align:start position:10%\n"
        "<v Roger>Hello</v> &amp; <b>world</b>\n\n"
        "00:04.000 --> 00:05.000\n"
        "Second line\n",
    )
    assert [(s.start, s.end, s.text) for s in parse_subtitle(path)] == [
        (1.0, 3.5, "Hello & world"),
        (4.0, 5.0, "Second line"),
    ]


def test_srt_crlf_and_repeated_captions_are_preserved(tmp_path: Path):
    path = _write(
        tmp_path,
        "1\r\n00:00:01,000 --> 00:00:02,000\r\nHello\r\n\r\n"
        "2\r\n00:00:02,000 --> 00:00:03,000\r\nHello\r\n\r\n"
        "3\r\n00:00:04,000 --> 00:00:05,000\r\nWorld\r\n",
        ".srt",
    )
    assert [(s.start, s.end, s.text) for s in parse_subtitle(path)] == [
        (1.0, 2.0, "Hello"),
        (2.0, 3.0, "Hello"),
        (4.0, 5.0, "World"),
    ]


def test_mm_ss_and_hh_mm_ss_forms(tmp_path: Path):
    path = _write(
        tmp_path,
        "WEBVTT\n\n"
        "00:01.000 --> 00:02.000\nA\n\n"
        "01:02:03.004 --> 01:02:04.005\nB\n",
    )
    assert [(s.start, s.end) for s in parse_subtitle(path)] == [(1.0, 2.0), (3723.004, 3724.005)]


@pytest.mark.parametrize(
    "stamp",
    [
        "00:00:01.000 --> nope",
        "00:00:01.000 --> 00:99:02.000",
        "00:00:01.000 --> 00:00:60.000",
        "00:00:01.000 --> 00:00:00.000",
    ],
)
def test_invalid_cues_raise(tmp_path: Path, stamp: str):
    path = _write(tmp_path, f"WEBVTT\n\n{stamp}\nText\n")
    with pytest.raises(ValueError):
        parse_subtitle(path)


def test_unsorted_cue_starts_raise(tmp_path: Path):
    path = _write(
        tmp_path,
        "WEBVTT\n\n"
        "00:00:05.000 --> 00:00:06.000\nA\n\n"
        "00:00:04.000 --> 00:00:05.000\nB\n",
    )
    with pytest.raises(ValueError, match="未按顺序"):
        parse_subtitle(path)


def test_note_can_contain_arrow_without_becoming_cue(tmp_path):
    path = _write(tmp_path, 'WEBVTT\n\nNOTE\n00:01.000 --> 00:02.000\nNot spoken\n\n00:03.000 --> 00:04.000\nalign: ordinary spoken text\n')
    assert [s.text for s in parse_subtitle(path)] == ['align: ordinary spoken text']
