# Validation record

This alpha is not an accuracy benchmark or evidence of community adoption.

Alpha 2: 75 tests passed in the pinned clean Python environment; TypeScript and Vite build passed. New checks ensure transcript/demo paths never initialize an LLM, validate WebVTT parsing and multiline edit round-trips, export actual transcript content in six formats, preserve ASR provenance, use updated source titles, retain uncertain references as unverified, and use the persisted model for health/unload. Forced CPU smoke on the development machine: 5-second audio, 2 segments, about 21.2 seconds. This is not a test of a machine without Vulkan drivers.

Live HTTP smoke with Ollama deliberately pointed at an unavailable loopback port: bundled demo completed in about 0.12 seconds after server startup; all six exports returned successfully; cross-site writes were rejected. This is not a cold application startup or first-time user study.

Checks include regression tests, checkpoint corruption/recovery, fake-model interrupted generation, local regeneration after edits, revision conflicts, legacy import, exports, TypeScript and Vite build.

Real local Ollama smoke: `qwen3.5:4b`, original 90-second SRT (`examples/checkpoints.srt`), one block, four paragraphs, zero missing structural citations; approximately 10.8 seconds on the development machine. This excludes ASR and does not establish factual accuracy. Runtime varies by machine and model.

```powershell
.\.venv\Scripts\python.exe scripts/smoke_local.py --model qwen3.5:4b --data-dir qa_output/my-smoke
```

Use an already downloaded model and an empty test directory. Generated files stay outside Git.

Local GPU smoke: 75-second audio, 24 transcript segments, approximately 5.8 seconds using whisper.cpp Vulkan on NVIDIA RTX 4070 (driver 32.0.16.1088). This checks execution, not transcript accuracy. The private smoke input is excluded from the repository.

A fresh Python 3.12 virtual environment successfully installed the complete pinned dependency set: 58 tests passed, TypeScript checks and Vite build passed. A Windows package built from that environment completed its executable self-test with exit code 0 (Whisper Vulkan, WASAPI loopback and Python dependencies).

DOCX structure/export is tested; visual page rendering was not checked because LibreOffice is unavailable on the development machine.

External installation testing, two-hour real-video quality, broad hardware coverage, broad remote-provider compatibility and community adoption are not established. Ten licensed videos and five external testers are targets, not completed results.

Future evaluations record source rights, language, duration, model, hardware, time, resource usage, structural citation validity, human-rated support, important-information coverage and terminology/number miscorrections. Compare baseline and candidate on identical inputs/settings. Publish failures and denominators. ID existence is not semantic support.
