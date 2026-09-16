# Changelog

## 2.0.0-alpha.3

- Open supported YouTube/Bilibili source videos at the selected subtitle time; retain Bilibili multipart selection.
- Keep timestamp links in transcript-only Word and Markdown exports.
- Switch existing notes to a collapsible topic map and export its Markdown outline, without another model or API call.
- Search materials by title, filename, author or URL; combine status and source filters. Older tasks remain searchable beyond the previous 100-item limit, with progressive rendering.
- Preserve missing-citation and stale-content warnings in maps/exports; load audio metadata before seeking.
- No new dependencies, model downloads, database migrations or automatic media moves.

## 2.0.0-alpha.2

- Start with a bundled example without Ollama, API keys or a GPU.
- Read/transcribe first, then optionally generate a lecture. Transcript-only tasks never initialize the LLM.
- Import WebVTT alongside SRT; export full transcript to TXT/VTT and readable Word/Markdown without generating a lecture.
- Select installed Ollama models in settings; model health, download, inference and unload now use the same selection.
- Explicit CPU transcription and CPU retry after ASR failure.
- Keep real-time subtitles collapsed until requested; show actionable processing failures in the workspace.
- Preserve original ASR provenance and validate subtitle timing strictly.
- Published releases build and attach a complete Windows ZIP and SHA256 record.

## 2.0.0-alpha.1

- Source-linked lecture workspace, reviewable subtitle corrections, revision conflicts, checkpoints and local regeneration.
- Windows setup, tests, CI, MIT license and contribution documentation.
