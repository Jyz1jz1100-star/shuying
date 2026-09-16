from videosummarizer.schemas import TranscriptSegment
from videosummarizer.text_utils import chunk_segments, format_timecode, safe_filename


def test_timecode_and_filename():
    assert format_timecode(3661.9) == "01:01:01"
    assert safe_filename('A/B:C*? "demo"') == 'A_B_C__ _demo_'
    assert safe_filename("CON") == "视频总结"


def test_chunking_preserves_segments_and_limits():
    segments = [TranscriptSegment(start=index * 60, end=(index + 1) * 60, text="内容" * 60) for index in range(20)]
    chunks = chunk_segments(segments, max_seconds=300, max_characters=500)
    assert [item for chunk in chunks for item in chunk] == segments
    assert all(chunk[-1].end - chunk[0].start <= 360 for chunk in chunks)
