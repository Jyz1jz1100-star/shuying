from __future__ import annotations

import math
import struct
import wave

from videosummarizer.whispercpp import MODEL_SPECS, _convert_to_wav, _write_wav_chunk


def test_whisper_profiles_are_multilingual_full_models():
    assert MODEL_SPECS["balanced"].name == "large-v3-turbo"
    assert MODEL_SPECS["accurate"].name == "large-v3"
    assert "q5" not in MODEL_SPECS["balanced"].filename
    assert "q5" not in MODEL_SPECS["accurate"].filename


def test_audio_conversion_and_chunk_geometry(tmp_path):
    source = tmp_path / "stereo.wav"
    converted = tmp_path / "mono.wav"
    chunk = tmp_path / "chunk.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(44100)
        frames = bytearray()
        for index in range(44100 * 2):
            sample = int(3000 * math.sin(2 * math.pi * 440 * index / 44100))
            frames.extend(struct.pack("<hh", sample, sample))
        output.writeframes(frames)

    _convert_to_wav(source, converted)
    _write_wav_chunk(converted, chunk, 0.5, 1.5)

    with wave.open(str(converted), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16000
        assert audio.getnframes() == 32000
    with wave.open(str(chunk), "rb") as audio:
        assert audio.getnframes() == 16000
