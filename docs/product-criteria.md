# Product criteria and iteration record

The product is judged by completing a useful task, not by preserving its current code structure.

| Goal | Acceptance scenario | Alpha 2 outcome |
| --- | --- | --- |
| Easy to start | Open an example without installing/configuring an AI service | Bundled original demo; no ASR or LLM calls |
| Useful independently | Read, correct, search and export existing subtitles without a model | Transcript-first mode; Markdown/Word contain full transcript when no lecture exists |
| Interoperable | Reuse subtitles from other transcription tools and ordinary players/editors | SRT/VTT import; SRT/VTT/TXT/Markdown/DOCX/JSON export |
| Hardware choice | Use CPU explicitly when GPU inference is unsuitable | Per-task device choice and CPU retry; tested on development machine, not every driverless machine |
| Model choice | Use an installed local model rather than a fixed large download | Ollama model discovery and persisted editable model; compatible API remains available |
| Recoverability | A model failure leaves the transcript useful | Workspace remains readable/exportable and displays the failure |

Existing solutions were reviewed first: [Buzz](https://chidiwilliams.github.io/buzz/docs) already offers offline transcription, playback, multiple engines and standard subtitle export. Shuying should interoperate with those outputs; basic transcription alone is not a sufficient differentiator. The focus here remains editable source-linked documents and reliable recovery.

This record measures implemented behavior, not adoption. Next evidence gaps: independent first-use sessions, time to first useful export on ordinary machines, long-video support accuracy, keyboard/screen-reader/browser UI testing, and macOS/Linux packaging. Do not claim general OS or driver compatibility from a single Windows machine.
