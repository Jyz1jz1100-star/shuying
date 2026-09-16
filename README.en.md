# Shuying 述影

**Turn video and audio into text you can read, search, and keep.**

Keep something useful from a course, interview, podcast, or recording. Shuying lets you transcribe speech, edit the text, and export it to your favorite tools. Optionally, turn the transcript into Chinese AI notes with links back to the source passages.

**[Download for Windows](https://github.com/Jyz1jz1100-star/shuying/releases/download/v2.0.0-alpha.2/Shuying-windows-x64.zip)** · [User guide (中文)](docs/user-guide.md) · [Report an issue](https://github.com/Jyz1jz1100-star/shuying/issues) · [中文](README.md)

Free and open source · Locally stored · Windows x64 · Alpha

## What can you do with it?

| When you want to… | Shuying helps you… |
| --- | --- |
| Revisit a course | Read the transcript, optionally create Chinese notes, and export to Word |
| Find a phrase from an interview or podcast | Search the text, check its timestamp, and replay it when local audio is available |
| Turn your recording into a document | Transcribe, correct the wording, and export an editable document |
| Fix existing subtitles | Import SRT / VTT and export corrected subtitles or plain text |

## From listening to something you can use

- **Read at your own pace.** Bring in local media, public video links, or existing subtitles.
- **Check the original words.** References in AI notes lead to the corresponding transcript passages.
- **See the structure first.** Switch existing notes to a collapsible topic map, select a node to find its source, or export a Markdown outline.
- **Keep your corrections.** Edit the transcript and update the affected notes; original text is retained.
- **Take your work with you.** Export Word, Markdown, TXT, SRT, VTT, or JSON. Without AI notes, Word and Markdown contain the full transcript.
- **Find your materials.** Search by title, filename, author, or URL, then filter by status and source.
- **Choose AI when you need it.** The example and existing subtitles need no model or API key. For notes, choose a local Ollama model or a compatible online service.

## Get started

1. Download the Windows ZIP above, extract the entire folder, and open `VideoSummarizer.exe`. Keep the other files alongside it. No Python or Node.js installation is needed. This alpha is unsigned.
2. Click **“先体验示例”** (try the example) to read, search, edit, and export without downloading a model.
3. Import your subtitles, audio, video, or a supported public video link. Start with the transcript; configure a model only if you want AI notes (“讲义” in the app).

Audio transcription needs a speech recognition model, downloaded on first use. GPU and explicit CPU modes are available; CPU is usually slower. Existing subtitles skip this step. The current interface and generated notes primarily target Chinese-language use.

## A few things to know

- **Privacy:** tasks and media copies stay on your machine. Local AI processing does not send content to an AI cloud service. Online AI mode sends the required text to your chosen provider, not the video or audio. Media and model downloads still use the network. Online providers may charge separately.
- **Compatibility:** Windows x64 only. Media: up to two hours and 2GB per item. UTF-8 SRT / VTT: up to 10MB. Public link support depends on the source website; authenticated, paid or DRM content, livestreams, and playlists are not supported.
- **Scope:** Shuying works with speech and subtitles, not images, slides, or handwriting in the video. AI notes can be wrong; references help you check them.

See the [user guide (中文)](docs/user-guide.md) for model setup, storage, and troubleshooting.

## Help improve Shuying

[Share a problem or request](https://github.com/Jyz1jz1100-star/shuying/issues) with what you wanted to do, where you got stuck, and your version. Remove private content and credentials from attachments.

For code, documentation, or translation contributions, see [Contributing](CONTRIBUTING.md) and the [development guide](docs/development.md). See [Changelog](CHANGELOG.md) for release changes.

Project code and original examples use the [MIT license](LICENSE). Bundled dependencies and models have their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
