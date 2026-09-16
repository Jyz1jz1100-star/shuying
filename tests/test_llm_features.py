import json
import os

import httpx
import pytest

from videosummarizer.config import Settings
from videosummarizer.llm_settings import (
    LLMRuntimeSettings,
    LLMSettingsError,
    LLMSettingsStore,
    normalize_api_base_url,
)
from videosummarizer.schemas import ProofreadBatch, ProofreadSegment, Transcript, TranscriptSegment
from videosummarizer.summarizer import OllamaError, OllamaSummarizer


def test_api_base_url_requires_https_except_loopback():
    assert normalize_api_base_url("https://api.example.com/v1/chat/completions") == "https://api.example.com/v1"
    assert normalize_api_base_url("https://api.openai.com") == "https://api.openai.com/v1"
    assert normalize_api_base_url("https://api.openai.com/chat/completions") == "https://api.openai.com/v1"
    assert normalize_api_base_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"
    with pytest.raises(LLMSettingsError):
        normalize_api_base_url("http://api.example.com/v1")
    with pytest.raises(LLMSettingsError):
        normalize_api_base_url("https://user:pass@example.com/v1")


def test_api_provider_cannot_be_saved_without_key(tmp_path):
    store = LLMSettingsStore(tmp_path / "llm_settings.json", "qwen")
    with pytest.raises(LLMSettingsError):
        store.save("openai_compatible", "https://api.example.com/v1", "model-x", None)


def test_local_model_persists_and_drives_health_and_unload(tmp_path, monkeypatch):
    store = LLMSettingsStore(tmp_path/'settings.json', 'default-model')
    store.save('local', '', '', None, 'small-model:latest')
    runtime = LLMSettingsStore(store.path, 'default-model').runtime('local')
    assert runtime.model == 'small-model:latest'
    calls = []
    monkeypatch.setattr(httpx, 'get', lambda *a, **kw: httpx.Response(200,
        json={'models':[{'name':'small-model:latest'}]}, request=httpx.Request('GET','http://localhost')))
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: calls.append(kw['json']))
    writer = OllamaSummarizer(Settings(ollama_model='default-model'), runtime)
    writer.ensure_model(lambda *a: pytest.fail('Existing model should not download'))
    writer.unload_model()
    assert calls[0]['model'] == runtime.model


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_api_key_is_dpapi_encrypted_and_can_be_reloaded(tmp_path):
    path = tmp_path / "llm_settings.json"
    store = LLMSettingsStore(path, "qwen3.5:9b-q4_K_M")
    public = store.save("openai_compatible", "https://api.example.com/v1", "model-x", "secret-value")
    assert public["has_api_key"] is True
    assert "secret-value" not in path.read_text(encoding="utf-8")
    assert store.runtime("openai_compatible").api_key == "secret-value"


def test_proofreading_preserves_timestamps_and_falls_back_for_missing_segments():
    class FakeProofreader(OllamaSummarizer):
        def _chat_model(self, model_type, prompt):
            assert model_type is ProofreadBatch
            assert '"index": 0' in prompt
            return ProofreadBatch(segments=[ProofreadSegment(index=0, text="OpenAI 发布了新模型。")])

    transcript = Transcript(
        language="zh,en",
        source="whisper_cpp",
        segments=[
            TranscriptSegment(start=1.25, end=3.5, text="open ai 发布了新模型"),
            TranscriptSegment(start=3.5, end=5.0, text="无法确认的原文"),
        ],
    )
    proofreader = FakeProofreader(
        Settings(),
        LLMRuntimeSettings(provider="local", model="qwen3.5:9b-q4_K_M"),
    )
    result = proofreader.proofread(transcript, lambda _progress, _message: None, lambda: None)
    assert [(item.start, item.end) for item in result.segments] == [(1.25, 3.5), (3.5, 5.0)]
    assert result.segments[0].text == "OpenAI 发布了新模型。"
    assert result.segments[1].text == "无法确认的原文"
    assert result.proofread_by == "qwen3.5:9b-q4_K_M"


def test_openai_compatible_falls_back_to_json_object(monkeypatch):
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json))
        request = httpx.Request("POST", url)
        if len(calls) == 1:
            return httpx.Response(400, json={"error": "json_schema unsupported"}, request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = OllamaSummarizer(
        Settings(),
        LLMRuntimeSettings(
            provider="openai_compatible",
            model="model-x",
            base_url="https://api.example.com/v1",
            api_key="secret-value",
        ),
    )
    client.test_connection()
    assert len(calls) == 2
    assert calls[0][2]["response_format"]["type"] == "json_schema"
    assert calls[1][2]["response_format"]["type"] == "json_object"
    assert calls[0][1]["Authorization"] == "Bearer secret-value"


def test_gpt5_omits_unsupported_temperature(monkeypatch):
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append(json)
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}]},
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = OllamaSummarizer(
        Settings(),
        LLMRuntimeSettings(
            provider="openai_compatible",
            model="gpt-5.6-luna",
            base_url="https://api.openai.com/v1",
            api_key="secret-value",
        ),
    )
    client.test_connection()
    assert "temperature" not in calls[0]
    assert calls[0]["messages"][0]["role"] == "system"
    assert calls[0]["messages"][1]["role"] == "user"
    assert calls[0]["response_format"]["type"] == "json_schema"


def test_openai_error_body_is_exposed_without_httpx_generic(monkeypatch):
    def fake_post(url, *, headers, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Unsupported value: temperature",
                    "type": "invalid_request_error",
                    "code": "unsupported_value",
                    "param": "temperature",
                }
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = OllamaSummarizer(
        Settings(),
        LLMRuntimeSettings(
            provider="openai_compatible",
            model="model-x",
            base_url="https://api.example.com/v1",
            api_key="secret-value",
        ),
    )
    with pytest.raises(OllamaError, match="HTTP 400.*Unsupported value: temperature") as caught:
        client.test_connection()
    assert "secret-value" not in str(caught.value)
