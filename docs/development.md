# Development guide

For using the downloadable app, start with the [README](../README.en.md). This document covers source installation, tests, and packaging.

## Windows setup

Requirements: Windows x64, Python 3.12 with the `py` launcher, Node.js 22.13+, and pnpm 11. GPU transcription requires compatible Vulkan hardware and drivers. Explicit CPU mode is also available. Subtitle-only work needs neither the transcription runtime nor an AI service.

```powershell
git clone https://github.com/Jyz1jz1100-star/shuying.git
cd shuying
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File .\run_dev.ps1
```

The setup script installs the locked dependencies, builds the frontend, and fetches the transcription runtime. Use `setup_windows.ps1 -SkipWhisper` for subtitle-only development. Import the [original sample](../examples/checkpoints.srt) or use the bundled example without a model.

`run_dev.ps1` opens the local app. For frontend changes, use `pnpm dev` with the backend running; the development server proxies API requests to the backend on port 8765.

Choose an installed Ollama model or configure a Chat Completions compatible API in the app. See the [user guide](user-guide.md) for configuration behavior. `OLLAMA_MODEL` can set the initial local model default.

## Tests and packaging

```powershell
.\.venv\Scripts\python.exe -m pytest -q
pnpm typecheck
node --experimental-strip-types --test tests/taskLibrary.test.mjs
pnpm build
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

Keep ordinary tests independent of model services by mocking model calls. To run an optional real-model check with an installed model and an empty test directory:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_local.py --model qwen3.5:4b --data-dir qa_output/my-smoke
```

Model output quality and runtime depend on the input, model, and hardware. Automated checks do not establish transcription accuracy or factual correctness.

The executable is `dist\VideoSummarizer\VideoSummarizer.exe`; distribute the complete directory. The Whisper runtime is fetched with a pinned version and SHA256. Model weights are downloaded separately and must not enter Git. Include third-party notices and licenses with distributions.

Python dependency ranges live in `requirements.txt`, with the tested Windows environment pinned in `requirements-lock.txt`. The frontend uses `pnpm-lock.yaml`. CI runs code checks; the packaging workflow builds archives and publishes assets for releases.

## Data and internals

Default data directory: `%LOCALAPPDATA%\VideoSummarizer`. Override with `VIDEOSUMMARIZER_DATA_DIR` for isolated development or testing. Never point destructive test cleanup at user data.

The application is a local, single-user loopback service. Do not expose it publicly. API keys are stored using Windows DPAPI. Task revision snapshots are stored under `history/`; there is no history-restore UI yet.

See [architecture](architecture.md) for processing, citations, and checkpoints, and [Contributing](../CONTRIBUTING.md) for review and documentation conventions.
