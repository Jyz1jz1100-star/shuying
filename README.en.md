# Shuying 述影

Local-first technical video notes with source-linked paragraphs, reviewable transcript corrections, and resumable processing.

[中文说明](README.md)

**Windows alpha.** Turn public video links, local media, or UTF-8 SRT into Chinese lecture notes. Inspect original transcripts, review corrections, replay available audio, and export Markdown, DOCX, SRT or JSON. References locate sources; they do not certify factual correctness.

Install Python 3.12, Node.js 22.13+ and pnpm 11 on Windows x64:

```powershell
git clone https://github.com/Jyz1jz1100-star/shuying.git
cd shuying
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
# Optional smaller model; requires Ollama:
$env:OLLAMA_MODEL='qwen3.5:4b'
ollama pull qwen3.5:4b
powershell -ExecutionPolicy Bypass -File .\run_dev.ps1
```

Import `examples/checkpoints.srt` for a no-ASR demonstration. `setup_windows.ps1 -SkipWhisper` skips the GPU runtime for subtitle-only use. Alternatively configure a Chat Completions compatible provider in the app. Only text is sent; API keys use Windows DPAPI.

Completed audio chunks, correction batches, and sections are checkpointed. Editing invalidates affected sections. Original text and revision snapshots are retained. Startup does not automatically resume paid calls.

Windows only; single-user loopback service. Limits: 2GB / two hours for media, 10MB for SRT. No visual understanding, authenticated content, playlists or cloud hosting. Media copies remain until cleared. GPU support requires compatible Vulkan drivers; not every GPU is validated.

See [validation](docs/validation.md) for actual checks and gaps. No external adoption or accuracy claims are made. [Architecture](docs/architecture.md), [contributing](CONTRIBUTING.md), [MIT](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md).
