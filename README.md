# 述影 Shuying

**把技术视频整理成可回查来源、可人工校订的讲义。**

Local-first technical video notes with source-linked paragraphs, reviewable transcript corrections, and resumable processing.

[English](README.en.md) · [架构](docs/architecture.md) · [验证记录](docs/validation.md) · [贡献指南](CONTRIBUTING.md)

> **2.0.0-alpha.1**：Windows 本地应用，正在寻找首批试用者。引用提供核查入口，不保证模型生成内容正确。尚无外部社区采用度或准确率结论。

## 工作流程

1. 粘贴公开视频链接，或导入视频、音频、UTF-8 SRT。
2. 优先使用人工字幕，否则用 whisper.cpp Vulkan 本地转写。
3. 生成中文讲义，保留专有名词，每段引用关联具体字幕片段。
4. 点击引用查看原始字幕与当前文本；有回听音频时可跳到对应位置。
5. 接受、拒绝或手动修改校对建议。原文保留，数字、否定词及部分技术词变化会被标记。
6. 更新受影响的章节，导出 Markdown、Word、SRT 或结构化 JSON。

转写、校对和讲义按块保存检查点。失败或取消后点击“继续处理”，复用依赖未变化的完成块。引用时间由程序根据真实片段 ID 计算。

首版还包含任务级术语表、修订历史文件、版本冲突检测、媒体单独清理、旧任务兼容，以及 Windows 系统声音实时字幕。

## Windows 开发安装

需要 Windows x64、Python 3.12、Node.js 22.13+ 和 pnpm 11。转写需要兼容 Vulkan 的 GPU 与驱动；SRT 导入不需要 GPU 或 Whisper 运行时。

```powershell
git clone https://github.com/Jyz1jz1100-star/shuying.git
cd shuying
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
```

总结模型二选一：

- **本地**：安装并启动 [Ollama](https://ollama.com/)。默认 `qwen3.5:9b-q4_K_M` 按需下载。较小模型可在启动前设置 `$env:OLLAMA_MODEL='qwen3.5:4b'`，建议先运行 `ollama pull qwen3.5:4b`。
- **API**：在“LLM 设置”填写 OpenAI 兼容地址、精确模型 ID 与密钥。远程地址必须为 HTTPS，请求格式为 `/v1/chat/completions`。

```powershell
powershell -ExecutionPolicy Bypass -File .\run_dev.ps1
```

浏览器会自动打开本地应用。先导入 [原创示例字幕](examples/checkpoints.srt)，无需下载视频或转写模型。仅处理字幕时可用 `setup_windows.ps1 -SkipWhisper` 跳过转写运行时下载。前端开发使用 `pnpm dev`，API 代理到本地后端。

## 限制与数据去向

- 仅支持 Windows x64、本地单用户，不要暴露到公网。
- 最长 2 小时；媒体最多 2GB，SRT 最多 10MB。不支持登录、付费、DRM、直播或播放列表，也不理解画面。
- 本地推理不会向 AI 云服务发送内容；视频和模型下载仍需要网络。
- API 模式向用户选择的服务商发送字幕和讲义所需文本，不发送视频或音频。密钥以 Windows DPAPI 加密保存。
- 数据保存在 `%LOCALAPPDATA%\VideoSummarizer`，可通过 `VIDEOSUMMARIZER_DATA_DIR` 覆盖。
- 媒体副本默认保留。“清理媒体副本”仅删除应用保存的副本；再次回听需要重新导入或下载，字幕与讲义继续保留。
- 修订历史保存在任务 `history/`；尚无历史恢复 UI 或时间轴拆分合并。
- 作者字幕任务未下载音频时，通过来源链接和文字核查。旧讲义不会自动补造引用，可以主动重新生成。

## 验证与打包

```powershell
.\.venv\Scripts\python.exe -m pytest -q
pnpm typecheck
pnpm build
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

输出 `dist\VideoSummarizer\VideoSummarizer.exe`，运行时保留完整目录。Whisper 运行时按固定版本和 SHA256 获取，模型不进入 Git。CI 验证代码，手动打包工作流生成测试包。

Python 依赖范围在 `requirements.txt`，已验证 Windows 环境的固定依赖在 `requirements-lock.txt`；前端使用 `pnpm-lock.yaml`。

## 参与

当前重点是可核查讲义与稳定恢复；外部试用、真实长视频评测和开源社区采用是下一阶段目标。CLI/MCP 等待实际接入需求。

欢迎提交复现步骤、版本、硬件、脱敏错误及允许公开的最小材料。不要上传密钥、私人视频、日志或任务数据库。

自有代码与原创示例采用 [MIT](LICENSE)。第三方软件和模型遵循各自许可，见 [第三方声明](THIRD_PARTY_NOTICES.md)。
