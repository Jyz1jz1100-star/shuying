from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
import wave
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pyaudiowpatch as pyaudio

from .config import Settings
from .summarizer import OllamaSummarizer
from .whispercpp import MODEL_SPECS, WhisperCppTranscriber, _free_loopback_port


logger = logging.getLogger(__name__)


def _display_device_name(name: str) -> str:
    cleaned = re.sub(r"\s*\[Loopback\]\s*$", "", name).strip()
    # Some PortAudio builds replace a Chinese device-name prefix with U+FFFD.
    return re.sub(r"^�+", "扬声器", cleaned)


def _resample_pcm16(data: bytes, channels: int, source_rate: int, target_rate: int = 16000) -> bytes:
    samples = np.frombuffer(data, dtype="<i2")
    usable = samples.size - samples.size % max(channels, 1)
    if usable <= 0:
        return b""
    frames = samples[:usable].reshape(-1, max(channels, 1)).astype(np.float32)
    mono = frames.mean(axis=1)
    if source_rate != target_rate:
        target_count = max(1, round(mono.size * target_rate / source_rate))
        source_positions = np.arange(mono.size, dtype=np.float64)
        target_positions = np.linspace(0, max(mono.size - 1, 0), target_count)
        mono = np.interp(target_positions, source_positions, mono)
    return np.clip(mono, -32768, 32767).astype("<i2").tobytes()


def _write_pcm_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(pcm)


class LiveSubtitleManager:
    def __init__(self, config: Settings):
        self.config = config
        self.transcriber = WhisperCppTranscriber(config)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._audio_stream: Any | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lines: deque[dict[str, Any]] = deque(maxlen=80)
        self._recent_text: deque[str] = deque(maxlen=8)
        self._next_id = 1
        self._status = "stopped"
        self._message = "尚未启动"
        self._error: str | None = None
        self._device_id = -1
        self._device_name = ""
        self._profile = "balanced"
        self._devices: list[dict[str, Any]] | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._status in {"starting", "running"}

    def list_devices(self, refresh: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            if self._devices is not None and not refresh:
                return [dict(device) for device in self._devices]
        try:
            with pyaudio.PyAudio() as audio:
                default_id = int(audio.get_default_wasapi_loopback()["index"])
                devices = [
                    {
                        "id": int(device["index"]),
                        "name": _display_device_name(str(device["name"])),
                        "is_default": int(device["index"]) == default_id,
                        "sample_rate": int(device["defaultSampleRate"]),
                        "channels": int(device["maxInputChannels"]),
                    }
                    for device in audio.get_loopback_device_info_generator()
                ]
            devices.sort(key=lambda item: (not item["is_default"], item["name"].lower()))
        except Exception:
            logger.exception("枚举 WASAPI 播放设备失败")
            devices = []
        with self._lock:
            self._devices = devices
        return [dict(device) for device in devices]

    def start(self, device_id: int, profile: str = "balanced") -> dict[str, Any]:
        if not self.transcriber.runtime_ready():
            raise RuntimeError("程序包中缺少 Whisper Vulkan 运行时")
        if profile not in MODEL_SPECS:
            profile = "balanced"
        devices = self.list_devices(refresh=True)
        if device_id == -1:
            selected = next((device for device in devices if device["is_default"]), None)
        else:
            selected = next((device for device in devices if int(device["id"]) == device_id), None)
        if selected is None:
            raise RuntimeError("没有找到可用的 Windows 播放设备")
        with self._lock:
            if self._status in {"starting", "running"}:
                raise RuntimeError("实时字幕已经在运行")
            self._stop_event.clear()
            self._lines.clear()
            self._recent_text.clear()
            self._next_id = 1
            self._device_id = int(selected["id"])
            self._device_name = str(selected["name"])
            self._profile = profile
            self._status = "starting"
            self._message = "正在准备 Whisper 模型"
            self._error = None
            self._worker = threading.Thread(target=self._run, name="live-subtitles", daemon=True)
            self._worker.start()
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        with self._lock:
            process = self._process
        if process is not None:
            self.transcriber._stop_process(process)
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=6)
        with self._lock:
            self._process = None
            self._audio_stream = None
            self._worker = None
            self._status = "stopped"
            self._message = "实时字幕已停止"
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self._status,
                "message": self._message,
                "error": self._error,
                "device_id": self._device_id,
                "device_name": self._device_name,
                "profile": self._profile,
                "lines": list(self._lines),
            }

    def _progress(self, _: int, message: str) -> None:
        with self._lock:
            self._message = message

    def _cancel_check(self) -> None:
        if self._stop_event.is_set():
            raise RuntimeError("实时字幕已停止")

    def _run(self) -> None:
        process: subprocess.Popen[bytes] | None = None
        log_handle = None
        chunk_path = self.config.data_dir / "live-subtitle-chunk.wav"
        try:
            try:
                OllamaSummarizer(self.config).unload_model()
            except Exception:
                logger.info("实时字幕启动前未能卸载 Ollama 模型", exc_info=True)
            model_path = self.transcriber.ensure_model(self._profile, self._progress, self._cancel_check)
            port = _free_loopback_port()
            log_handle = (self.config.data_dir / "live-whisper-vulkan.log").open("ab")
            command = [
                str(self.transcriber.executable), "-m", model_path.name, "-t", str(self.config.cpu_threads),
                "-bs", "3", "-bo", "3", "-l", "auto", "--host", "127.0.0.1", "--port", str(port), "-sns",
            ]
            process = subprocess.Popen(
                command,
                cwd=str(model_path.parent),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self._lock:
                self._process = process
                self._message = "正在把 Whisper 模型加载到 Radeon GPU"
            self._wait_for_server(process, port)
            self._capture_loop(process, port, chunk_path)
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.exception("实时字幕失败")
                with self._lock:
                    self._status = "error"
                    self._message = "实时字幕运行失败"
                    self._error = str(exc)
        finally:
            if process is not None:
                self.transcriber._stop_process(process)
            if log_handle is not None:
                log_handle.close()
            try:
                chunk_path.unlink()
            except OSError:
                pass
            with self._lock:
                self._process = None
                self._audio_stream = None
                if self._stop_event.is_set():
                    self._status = "stopped"
                    self._message = "实时字幕已停止"

    def _wait_for_server(self, process: subprocess.Popen[bytes], port: int) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            self._cancel_check()
            if process.poll() is not None:
                raise RuntimeError("Whisper Vulkan 服务启动失败")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        raise RuntimeError("Whisper Vulkan 模型加载超时")

    def _capture_loop(self, process: subprocess.Popen[bytes], port: int, chunk_path: Path) -> None:
        with pyaudio.PyAudio() as audio:
            device = audio.get_device_info_by_index(self._device_id)
            rate = int(device["defaultSampleRate"])
            channels = max(1, int(device["maxInputChannels"]))
            frames_per_buffer = 1024
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=self._device_id,
                frames_per_buffer=frames_per_buffer,
            )
            with self._lock:
                self._audio_stream = stream
                self._status = "running"
                self._message = f"正在转录：{self._device_name}"
            raw = bytearray()
            bytes_per_frame = channels * 2
            window_bytes = int(rate * 4.0) * bytes_per_frame
            overlap_bytes = int(rate * 0.4) * bytes_per_frame
            try:
                while not self._stop_event.is_set():
                    raw.extend(stream.read(frames_per_buffer, exception_on_overflow=False))
                    if len(raw) < window_bytes:
                        continue
                    window = bytes(raw[:window_bytes])
                    raw = bytearray(window[-overlap_bytes:] + raw[window_bytes:])
                    pcm = _resample_pcm16(window, channels, rate)
                    if not pcm or self._is_silent(pcm):
                        continue
                    _write_pcm_wav(chunk_path, pcm)
                    payload = self.transcriber._request_interruptibly(
                        f"http://127.0.0.1:{port}", chunk_path, process, self._cancel_check,
                    )
                    for item in payload.get("segments") or []:
                        text = str(item.get("text") or "").strip()
                        if text:
                            self._append_line(text)
            finally:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass

    @staticmethod
    def _is_silent(pcm: bytes) -> bool:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        return samples.size == 0 or float(np.sqrt(np.mean(samples * samples))) < 75.0

    def _append_line(self, text: str) -> None:
        with self._lock:
            if text in self._recent_text:
                return
            self._lines.append({
                "id": self._next_id,
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "text": text,
            })
            self._recent_text.append(text)
            self._next_id += 1
