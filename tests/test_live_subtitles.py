import numpy as np

from videosummarizer.live_subtitles import _display_device_name, _resample_pcm16


def test_display_device_name_is_a_playback_name():
    assert _display_device_name("Headphones [Loopback]") == "Headphones"
    assert _display_device_name("������ (Audio) [Loopback]") == "扬声器 (Audio)"


def test_resample_stereo_48k_to_mono_16k():
    frames = np.column_stack((np.arange(4800, dtype=np.int16), np.arange(4800, dtype=np.int16)))
    output = _resample_pcm16(frames.astype("<i2").tobytes(), channels=2, source_rate=48000)
    assert len(output) == 1600 * 2
