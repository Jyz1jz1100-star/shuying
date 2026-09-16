# Third-party notices

Shuying's MIT license applies to its own source, not to third-party runtimes,
models, codecs or dependencies. The source checkout does not include model
weights or vendor binaries. Build-time `scripts/collect_licenses.py` collects
installed package license notices into the Windows package's `licenses/` folder.
The Python dependency closure is recorded in requirements-lock.txt; frontend
dependencies are recorded in pnpm-lock.yaml.

PyAV uses FFmpeg libraries distributed with its wheel. FFmpeg components retain
their upstream licenses and build-specific obligations; consult the PyAV/FFmpeg
notices included by the installed wheel before redistributing a modified build.
Ollama is a separately installed application. Whisper/Qwen model files are
downloaded separately and retain their respective model licenses.

## whisper.cpp Vulkan runtime

The bundled Windows Vulkan runtime is pinned to `lemonade-sdk/whisper.cpp-rocm` v1.8.4:

- Source: https://github.com/lemonade-sdk/whisper.cpp-rocm/tree/v1.8.4
- Binary asset: `whisper-v1.8.4-windows-vulkan-x64.zip`
- Asset SHA-256: `e0d20a0f92e31b98adc0faf71172efc810b701e6391a9d858ca045bff26f77cd`
- Upstream: https://github.com/ggml-org/whisper.cpp
- License: MIT

Whisper model files are downloaded on demand from the official `ggerganov/whisper.cpp` Hugging Face repository and verified against the upstream SHA-1 values before use.

## PyAudioWPatch

Windows playback-device capture uses PyAudioWPatch 0.2.12.8:

- Source: https://github.com/s0d3s/PyAudioWPatch
- Purpose: PortAudio with Windows WASAPI loopback support
- License: Apache-2.0

## srt

SubRip subtitle composition and validation uses srt 3.5.3:

- Source: https://github.com/cdown/srt
- License: MIT
