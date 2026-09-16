from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class LLMSettingsError(ValueError):
    pass


@dataclass(frozen=True)
class LLMRuntimeSettings:
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""

    @property
    def label(self) -> str:
        return self.model if self.provider == "local" else f"API · {self.model}"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect_secret(value: str) -> str:
    if os.name != "nt":
        raise LLMSettingsError("API 密钥持久化仅支持 Windows DPAPI")
    raw = value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "VideoSummarizer LLM API key",
        None,
        None,
        None,
        0x1,
        ctypes.byref(target),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        encrypted = ctypes.string_at(target.pbData, target.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(target.pbData)


def _unprotect_secret(value: str) -> str:
    if not value:
        return ""
    if os.name != "nt":
        raise LLMSettingsError("API 密钥解密仅支持 Windows DPAPI")
    raw = base64.b64decode(value)
    buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(target.pbData)


def normalize_api_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LLMSettingsError("API 地址必须是有效的 HTTP/HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LLMSettingsError("API 地址不能包含账号、密码、查询参数或片段")
    loopback = parsed.hostname.lower() in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not loopback:
        raise LLMSettingsError("远程 LLM API 必须使用 HTTPS；HTTP 仅允许本机地址")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if parsed.hostname.lower() == "api.openai.com" and path in {"", "/"}:
        path = "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class LLMSettingsStore:
    def __init__(self, path: Path, local_model: str):
        self.path = path
        self.local_model = local_model
        self._lock = threading.RLock()

    def public(self) -> dict:
        payload = self._read()
        return {
            "default_provider": payload["default_provider"],
            "local_model": payload['local_model'],
            "api_base_url": payload["api_base_url"],
            "api_model": payload["api_model"],
            "has_api_key": bool(payload.get("api_key_protected")),
        }

    def save(
        self,
        default_provider: str,
        api_base_url: str,
        api_model: str,
        api_key: str | None,
        local_model: str | None = None,
    ) -> dict:
        if default_provider not in {"local", "openai_compatible"}:
            raise LLMSettingsError("不支持的 LLM 类型")
        candidate_url = api_base_url if api_base_url.strip() or default_provider != 'local' else self._read()['api_base_url']
        normalized_url = normalize_api_base_url(candidate_url)
        model = api_model.strip()
        if default_provider == "openai_compatible" and not model:
            raise LLMSettingsError("使用 API 时必须填写模型名称")
        with self._lock:
            previous = self._read()
            selected_model = (local_model if local_model is not None else previous['local_model']).strip()
            if not selected_model or len(selected_model) > 200 or any(c.isspace() for c in selected_model):
                raise LLMSettingsError('本地模型名称不能为空、包含空白或超过 200 字符')
            protected = previous.get("api_key_protected", "")
            if api_key is not None and api_key.strip():
                protected = _protect_secret(api_key.strip())
            if default_provider == "openai_compatible" and not protected:
                raise LLMSettingsError("使用 API 时必须填写 API Key")
            payload = {
                "default_provider": default_provider,
                "local_model": selected_model,
                "api_base_url": normalized_url,
                "api_model": model,
                "api_key_protected": protected,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        return self.public()

    def runtime(self, provider: str) -> LLMRuntimeSettings:
        if provider == "local":
            return LLMRuntimeSettings(provider="local", model=self._read()['local_model'])
        if provider != "openai_compatible":
            raise LLMSettingsError("不支持的 LLM 类型")
        payload = self._read()
        model = str(payload.get("api_model") or "").strip()
        protected = str(payload.get("api_key_protected") or "")
        if not model or not protected:
            raise LLMSettingsError("LLM API 尚未配置完整，请先填写模型和 API Key")
        return LLMRuntimeSettings(
            provider=provider,
            model=model,
            base_url=normalize_api_base_url(str(payload["api_base_url"])),
            api_key=_unprotect_secret(protected),
        )

    def runtime_for_test(self, api_base_url: str, api_model: str, api_key: str | None) -> LLMRuntimeSettings:
        payload = self._read()
        key = (api_key or "").strip()
        if not key and payload.get("api_key_protected"):
            key = _unprotect_secret(str(payload["api_key_protected"]))
        if not key:
            raise LLMSettingsError("请填写 API Key，或先保存已有密钥")
        model = api_model.strip()
        if not model:
            raise LLMSettingsError("请填写 API 模型名称")
        return LLMRuntimeSettings(
            provider="openai_compatible",
            model=model,
            base_url=normalize_api_base_url(api_base_url),
            api_key=key,
        )

    def _read(self) -> dict:
        defaults = {
            "local_model": self.local_model,
            "default_provider": "local",
            "api_base_url": "https://api.openai.com/v1",
            "api_model": "",
            "api_key_protected": "",
        }
        with self._lock:
            if not self.path.is_file():
                return defaults
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return defaults
        return {**defaults, **payload}
