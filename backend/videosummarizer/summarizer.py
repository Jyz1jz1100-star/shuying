from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings
from .llm_settings import LLMRuntimeSettings
from .schemas import (
    ArticleDocument,
    ArticleSection,
    ChunkSummary,
    ProofreadBatch,
    SourceMetadata,
    Transcript,
    TranscriptSegment,
    VideoSummary,
)
from .text_utils import chunk_segments, transcript_lines


T = TypeVar("T", bound=BaseModel)
ProgressCallback = Callable[[int, str], None]


class OllamaError(RuntimeError):
    pass


def _upstream_error(response: httpx.Response, secret: str = "") -> OllamaError:
    """Turn an upstream error response into a useful, secret-free message."""
    detail = ""
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            fields = [error.get("message"), error.get("type"), error.get("code"), error.get("param")]
            detail = "；".join(str(item) for item in fields if item)
        elif isinstance(error, str):
            detail = error
        elif payload.get("message"):
            detail = str(payload["message"])
    if not detail:
        detail = "上游未提供错误详情"
    if secret:
        detail = detail.replace(secret, "[REDACTED]")
    return OllamaError(f"LLM API 返回 HTTP {response.status_code}：{detail[:800]}")


class _ConnectionCheck(BaseModel):
    ok: bool


class OllamaSummarizer:
    def __init__(self, config: Settings, runtime: LLMRuntimeSettings | None = None):
        self.config = config
        self.runtime = runtime or LLMRuntimeSettings(provider="local", model=config.ollama_model)

    def health(self) -> tuple[bool, bool]:
        if self.runtime.provider != "local":
            return True, bool(self.runtime.api_key and self.runtime.model and self.runtime.base_url)
        try:
            response = httpx.get(f"{self.config.ollama_url}/api/tags", timeout=3)
            response.raise_for_status()
            models = response.json().get("models", [])
            names = {item.get("name") or item.get("model") for item in models}
            return True, self.config.ollama_model in names
        except Exception:
            return False, False

    def ensure_model(self, progress: ProgressCallback, cancel_check: Callable[[], None] | None = None) -> None:
        if self.runtime.provider != "local":
            if not self.runtime.api_key or not self.runtime.model or not self.runtime.base_url:
                raise OllamaError("LLM API 尚未配置完整")
            return
        cancel_check = cancel_check or (lambda: None)
        ready, model_ready = self.health()
        if not ready:
            raise OllamaError("Ollama 未运行，请启动 Ollama 后重试")
        if model_ready:
            return
        progress(12, f"首次使用：正在下载 {self.config.ollama_model} 本地模型")
        try:
            with httpx.stream("POST", f"{self.config.ollama_url}/api/pull", json={"model": self.config.ollama_model, "stream": True}, timeout=None) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    cancel_check()
                    if not line:
                        continue
                    payload = json.loads(line)
                    total, completed = payload.get("total"), payload.get("completed")
                    if total and completed:
                        percent = 12 + int(9 * min(1, completed / total))
                        progress(percent, f"首次使用：正在下载本地模型 {int(completed/total*100)}%")
                    if payload.get("error"):
                        raise OllamaError(payload["error"])
        except httpx.HTTPError as exc:
            raise OllamaError(f"本地总结模型下载失败：{exc}") from exc

    def unload_model(self) -> None:
        """Release this application's Ollama model and its GPU KV cache."""
        if self.runtime.provider != "local":
            return
        try:
            httpx.post(
                f"{self.config.ollama_url}/api/generate",
                json={"model": self.config.ollama_model, "keep_alive": 0},
                timeout=10,
            )
        except httpx.HTTPError:
            pass

    def test_connection(self) -> None:
        result = self._chat_model(_ConnectionCheck, "返回 {\"ok\": true}，不要添加其他内容。")
        if not result.ok:
            raise OllamaError("API 已响应，但未通过结构化输出测试")

    def proofread(
        self,
        transcript: Transcript,
        progress: ProgressCallback,
        cancel_check: Callable[[], None],
    ) -> Transcript:
        if transcript.source == "human_subtitles":
            return transcript
        indexed = list(enumerate(transcript.segments))
        batches: list[list[tuple[int, TranscriptSegment]]] = []
        current: list[tuple[int, TranscriptSegment]] = []
        characters = 0
        for item in indexed:
            estimated = len(item[1].text) + 24
            if current and (len(current) >= 80 or characters + estimated > 7000):
                batches.append(current)
                current = []
                characters = 0
            current.append(item)
            characters += estimated
        if current:
            batches.append(current)
        if not batches:
            raise OllamaError("没有可校对的语音转写内容")

        corrected: dict[int, str] = {}
        for batch_index, batch in enumerate(batches, start=1):
            cancel_check()
            progress(
                59 + int(8 * (batch_index - 1) / len(batches)),
                f"正在校对字幕第 {batch_index}/{len(batches)} 批",
            )
            payload = [{"index": index, "text": segment.text} for index, segment in batch]
            prompt = (
                "你是严格的多语言语音转写校对员。逐条修正下面 Whisper 转写中的明显错字、同音词、英文拼写、专有名词、"
                "大小写和标点断句。一个视频可能是中文、英文或中英混合：保持每条原本语言，不翻译，不总结，不润色观点，"
                "不添加原文没有的信息。必须保留每个 index，不能合并、拆分、删除或新增字幕段。无法确信时保留原文。\n\n"
                f"待校对字幕：{json.dumps(payload, ensure_ascii=False)}"
            )
            result = self._chat_model(ProofreadBatch, prompt)
            expected = {index for index, _segment in batch}
            seen: set[int] = set()
            for item in result.segments:
                if item.index in expected and item.index not in seen and item.text.strip():
                    corrected[item.index] = item.text.strip()
                    seen.add(item.index)

        segments = [
            TranscriptSegment(start=item.start, end=item.end, text=corrected.get(index, item.text))
            for index, item in indexed
        ]
        progress(68, "字幕校对完成，时间轴已核对")
        return Transcript(
            language=transcript.language,
            source=transcript.source,
            segments=segments,
            proofread_by=self.runtime.label,
        )

    def summarize(self, transcript: Transcript, metadata: SourceMetadata, progress: ProgressCallback, cancel_check: Callable[[], None]) -> VideoSummary:
        chunks = chunk_segments(transcript.segments, self.config.chunk_seconds, self.config.chunk_characters)
        if not chunks:
            raise OllamaError("没有足够的语音或字幕内容可供总结")
        partials: list[ChunkSummary] = []
        for index, chunk in enumerate(chunks, start=1):
            cancel_check()
            progress(70 + int(14 * (index - 1) / len(chunks)), f"正在整理第 {index}/{len(chunks)} 个内容片段")
            prompt = (
                "你是严谨的视频内容整理员。仅根据下面带时间戳的转写输出中文结构化摘要；不得补充原文没有的事实，无法确定时写入 caveats。"
                "时间戳必须来自输入。action_items 只包含视频明确提出的行动。\n\n" + transcript_lines(chunk)
            )
            partials.append(self._chat_model(ChunkSummary, prompt))
        cancel_check()
        progress(85, "正在汇总章节、观点和行动项")
        final_prompt = (
            "你是严谨的中文编辑。根据分段摘要生成整段视频的最终结构化总结。去除重复内容；所有关键观点和章节保留可追溯时间戳；"
            "不得写入输入中不存在的事实。标题简洁，overview 使用连贯中文。source 字段先按提供的元数据填写。\n\n"
            f"来源元数据：{metadata.model_dump_json()}\n\n分段摘要：{json.dumps([item.model_dump() for item in partials], ensure_ascii=False)}"
        )
        summary = self._chat_model(VideoSummary, final_prompt)
        summary.source = metadata
        return summary

    def write_article(
        self,
        transcript: Transcript,
        metadata: SourceMetadata,
        summary: VideoSummary,
        progress: ProgressCallback,
        cancel_check: Callable[[], None],
    ) -> ArticleDocument:
        chunks = chunk_segments(transcript.segments, self.config.chunk_seconds, self.config.chunk_characters)
        if not chunks:
            raise OllamaError("没有足够的字幕内容可改写为文章")
        sections: list[ArticleSection] = []
        for index, chunk in enumerate(chunks, start=1):
            cancel_check()
            progress(88 + int(6 * (index - 1) / len(chunks)), f"正在把字幕改写为文章第 {index}/{len(chunks)} 节")
            prompt = (
                "你是忠实而成熟的中文长文编辑。把下面带时间戳的字幕整理为可独立阅读的完整文章章节。"
                "这不是摘要：尽量保留原文中所有有信息量的事实、数字、例子、比较、论证、条件、保留意见和结论；"
                "只删除口头禅、无意义重复、寒暄和字幕断句。修复明显的同音转写错误只能依据上下文，不确定时保留原词。"
                "英文内容写成自然中文，但产品名、模型名、人名等专有名词保留原文。不得添加字幕中不存在的事实或评价。"
                "paragraphs 每项是一段完整连贯的正文，不要使用项目符号、Markdown、时间戳或‘视频中提到’等转述腔。"
                "heading 应概括本节主题。start_seconds/end_seconds 先按输入首尾时间填写。\n\n"
                + transcript_lines(chunk)
            )
            section = self._chat_model(ArticleSection, prompt)
            section.start_seconds = chunk[0].start
            section.end_seconds = chunk[-1].end
            section.paragraphs = [paragraph.strip() for paragraph in section.paragraphs if paragraph.strip()]
            if not section.paragraphs:
                raise OllamaError(f"文章第 {index} 节没有生成有效正文")
            sections.append(section)
        cancel_check()
        progress(93, "完整文章正文已整理")
        return ArticleDocument(
            title=summary.title,
            lead=summary.one_sentence_summary,
            sections=sections,
            source=metadata,
        )

    def _chat_model(self, model_type: type[T], prompt: str) -> T:
        schema = model_type.model_json_schema()
        messages = [
            {"role": "system", "content": "只输出符合 JSON Schema 的 JSON。不要输出 Markdown，不要暴露思考过程。"},
            {"role": "user", "content": prompt + "\n\nJSON Schema：" + json.dumps(schema, ensure_ascii=False)},
        ]
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                content = self._request_content(messages, schema)
                return model_type.model_validate_json(content)
            except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                messages.append({"role": "user", "content": "上次输出未通过结构校验。请修正并只返回合法 JSON，字段必须完整。"})
        raise OllamaError(f"LLM 两次未能生成有效的结构化内容：{last_error}")

    def _request_content(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        if self.runtime.provider == "local":
            response = httpx.post(
                f"{self.config.ollama_url}/api/chat",
                json={
                    "model": self.runtime.model,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                    "format": schema,
                    "keep_alive": "10m",
                    "options": {"temperature": 0, "num_ctx": 32768},
                },
                timeout=600,
            )
            response.raise_for_status()
            return str(response.json()["message"]["content"])

        endpoint = f"{self.runtime.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.runtime.api_key}", "Content-Type": "application/json"}
        base_payload: dict[str, Any] = {
            "model": self.runtime.model,
            "messages": messages,
            "stream": False,
        }
        # GPT-5 models only accept their default temperature (1); sending 0
        # causes a 400 even though the rest of the Chat Completions payload is
        # valid. Keep deterministic temperature for older and compatible APIs.
        if not self.runtime.model.lower().startswith("gpt-5"):
            base_payload["temperature"] = 0
        formats: list[dict[str, Any] | None] = [
            {
                "type": "json_schema",
                "json_schema": {"name": "video_summarizer_result", "strict": True, "schema": schema},
            },
            {"type": "json_object"},
            None,
        ]
        response: httpx.Response | None = None
        for response_format in formats:
            payload = dict(base_payload)
            if response_format is not None:
                payload["response_format"] = response_format
            response = httpx.post(endpoint, headers=headers, json=payload, timeout=600)
            if response.status_code not in {400, 404, 422}:
                break
        assert response is not None
        if response.is_error:
            raise _upstream_error(response, self.runtime.api_key)
        content = response.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
        return str(content)
