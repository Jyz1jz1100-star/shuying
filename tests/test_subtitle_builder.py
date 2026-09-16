import srt

from videosummarizer.schemas import Transcript, TranscriptSegment
from videosummarizer.subtitle_builder import build_srt


def test_build_srt_contains_all_timestamped_segments(tmp_path):
    transcript = Transcript(
        language="zh,en",
        source="whisper_cpp",
        segments=[
            TranscriptSegment(start=0.25, end=2.5, text="第一句"),
            TranscriptSegment(start=3661.125, end=3664.0, text="second line\ncontinued"),
        ],
    )
    output = build_srt(transcript, '示例:/视频', tmp_path)
    parsed = list(srt.parse(output.read_text(encoding="utf-8-sig")))
    assert "完整字幕" in output.name
    assert [item.content for item in parsed] == ["第一句", "second line\ncontinued"]
    assert parsed[1].start.total_seconds() == 3661.125
