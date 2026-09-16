from __future__ import annotations

import hashlib
import json
import logging
import socket
import subprocess
import time
import wave
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import av
import httpx

from .config import Settings
from .schemas import Transcript, TranscriptSegment
from .checkpoints import Checkpoints, fingerprint, file_fingerprint


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, str], None]
CancelCheck = Callable[[], None]


class WhisperCppError(RuntimeError):
    pass


@dataclass(frozen=True)
class WhisperModelSpec:
    profile: str
    name: str
    filename: str
    url: str
    sha1: str
    size_gib: float


MODEL_SPECS = {
    "balanced": WhisperModelSpec(
        profile="balanced",
        name="large-v3-turbo",
        filename="ggml-large-v3-turbo.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin",
        sha1="4af2b29d7ec73d781377bfd1758ca957a807e941",
        size_gib=1.5,
    ),
    "accurate": WhisperModelSpec(
        profile="accurate",
        name="large-v3",
        filename="ggml-large-v3.bin",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin",
        sha1="ad82bf6a9043ceed055076d0fd39f5f186ff8062",
        size_gib=2.9,
    ),
}


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _convert_to_wav(input_path: Path, output_path: Path) -> None:
    with av.open(str(input_path)) as source, av.open(str(output_path), mode="w", format="wav") as target:
        stream = target.add_stream("pcm_s16le", rate=16000)
        stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in source.decode(audio=0):
            for converted in resampler.resample(frame):
                for packet in stream.encode(converted):
                    target.mux(packet)
        for converted in resampler.resample(None):
            for packet in stream.encode(converted):
                target.mux(packet)
        for packet in stream.encode(None):
            target.mux(packet)


def _write_wav_chunk(source_path: Path, target_path: Path, start_seconds: float, end_seconds: float) -> None:
    with wave.open(str(source_path), "rb") as source:
        rate = source.getframerate()
        start_frame = max(0, int(start_seconds * rate))
        end_frame = min(source.getnframes(), int(end_seconds * rate))
        source.setpos(start_frame)
        frames = source.readframes(max(0, end_frame - start_frame))
        with wave.open(str(target_path), "wb") as target:
            target.setparams(source.getparams())
            target.writeframes(frames)


class WhisperCppTranscriber:
    def __init__(self, config: Settings):
        self.config = config

    @property
    def executable(self) -> Path:
        return self.config.whisper_runtime_dir / "whisper-server.exe"

    def runtime_ready(self) -> bool:
        return self.executable.is_file() and (self.config.whisper_runtime_dir / "ggml-vulkan.dll").is_file()

    def ensure_model(self, profile: str, progress: ProgressCallback, cancel_check: CancelCheck) -> Path:
        spec = MODEL_SPECS.get(profile, MODEL_SPECS["balanced"])
        target = self.config.models_dir / spec.filename
        if target.is_file() and _sha1(target) == spec.sha1:
            return target
        if target.exists():
            target.unlink()
        part = target.with_suffix(target.suffix + ".part")
        existing = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        progress(38, f"首次使用：正在下载 Whisper {spec.name}（约 {spec.size_gib:.1f}GB）")
        try:
            with httpx.stream("GET", spec.url, headers=headers, follow_redirects=True, timeout=None) as response:
                if existing and response.status_code != 206:
                    existing = 0
                response.raise_for_status()
                content_length = int(response.headers.get("content-length") or 0)
                total = existing + content_length if content_length else 0
                mode = "ab" if existing else "wb"
                with part.open(mode) as handle:
                    downloaded = existing
                    for block in response.iter_bytes(1024 * 1024):
                        cancel_check()
                        handle.write(block)
                        downloaded += len(block)
                        if total:
                            percent = min(100, int(downloaded / total * 100))
                            progress(38 + int(5 * downloaded / total), f"正在下载 Whisper {spec.name} {percent}%")
        except httpx.HTTPError as exc:
            raise WhisperCppError(f"Whisper 模型下载失败：{exc}") from exc
        progress(43, "正在校验 Whisper 模型")
        if _sha1(part) != spec.sha1:
            try:
                part.unlink()
            except OSError:
                pass
            raise WhisperCppError("Whisper 模型校验失败，请删除模型临时文件后重试")
        part.replace(target)
        return target

    def transcribe(
        self,
        audio_path: Path,
        profile: str,
        progress: ProgressCallback,
        cancel_check: CancelCheck,
        job_dir: Path,
    ) -> Transcript:
        if not self.runtime_ready():
            raise WhisperCppError("程序包中缺少 Whisper Vulkan 运行时")
        model_path = self.ensure_model(profile, progress, cancel_check)
        wav_path = job_dir / "transcribe.wav"
        chunk_path = job_dir / "transcribe-chunk.wav"
        progress(44, "正在准备 16kHz 单声道音频")
        cache = Checkpoints(job_dir / 'checkpoints')
        audio_key = fingerprint({'sha256': file_fingerprint(audio_path), 'profile': profile,
                                 'seconds': self.config.transcription_chunk_seconds,
                                 'overlap': self.config.transcription_overlap_seconds, 'version': 2})
        wav_key = cache.load('wav', audio_key)
        if not wav_path.exists() or wav_key is None:
            temporary_wav = job_dir / 'transcribe-pending.wav'
            _convert_to_wav(audio_path, temporary_wav)
            temporary_wav.replace(wav_path)
            cache.save('wav', audio_key, {'ready': True})
        cancel_check()

        with wave.open(str(wav_path), "rb") as source:
            duration = source.getnframes() / max(source.getframerate(), 1)
        if duration <= 0:
            raise WhisperCppError("音轨中没有可转写的音频")

        port = _free_loopback_port()
        log_path = job_dir / "whisper-vulkan.log"
        log_handle = log_path.open("ab")
        command = [
            str(self.executable), "-m", model_path.name, "-t", str(self.config.cpu_threads),
            "-bs", "5", "-bo", "5", "-l", "auto", "--host", "127.0.0.1", "--port", str(port),
            "-sns",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command,
            # whisper.cpp's Windows argv conversion is not Unicode-safe for model
            # paths. Use the model directory as cwd and pass an ASCII filename.
            # Windows still resolves the runtime DLLs beside whisper-server.exe.
            cwd=str(model_path.parent),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            progress(45, "正在把 Whisper 模型加载到 Vulkan GPU")
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                cancel_check()
                if process.poll() is not None:
                    raise WhisperCppError(f"Whisper Vulkan 服务启动失败，请查看 {log_path.name}")
                try:
                    if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
            else:
                raise WhisperCppError("Whisper Vulkan 模型加载超时")

            segments: list[TranscriptSegment] = []
            languages: list[str] = []
            chunk_seconds = float(self.config.transcription_chunk_seconds)
            overlap = float(self.config.transcription_overlap_seconds)
            nominal_start = 0.0
            index = 0
            total_chunks = max(1, int((duration + chunk_seconds - 0.001) // chunk_seconds))
            while nominal_start < duration:
                cancel_check()
                actual_start = max(0.0, nominal_start - (overlap if nominal_start else 0.0))
                actual_end = min(duration, nominal_start + chunk_seconds)
                index += 1
                progress_value = 46 + int(12 * (index - 1) / total_chunks)
                progress(progress_value, f"GPU 转写第 {index}/{total_chunks} 段（自动识别中英语言）")
                chunk_key = fingerprint({'input': audio_key, 'start': actual_start, 'end': actual_end})
                payload = cache.load(f'audio{index:05d}', chunk_key)
                if payload is None:
                    _write_wav_chunk(wav_path, chunk_path, actual_start, actual_end)
                    payload = self._request_interruptibly(base_url, chunk_path, process, cancel_check)
                    for item in payload.get('segments') or []:
                        if item.get('text', '').strip():
                            TranscriptSegment(start=float(item.get('start', 0)), end=float(item.get('end', 0)), text=item['text'])
                    cache.save(f'audio{index:05d}', chunk_key, payload)
                language = str(payload.get("language") or payload.get("detected_language") or "unknown")
                if language not in languages:
                    languages.append(language)
                for item in payload.get("segments") or []:
                    text = str(item.get("text") or "").strip()
                    if not text:
                        continue
                    start = actual_start + float(item.get("start") or 0)
                    end = actual_start + float(item.get("end") or item.get('start') or 0)
                    if nominal_start and (start + end) / 2 < nominal_start:
                        continue
                    segments.append(TranscriptSegment(start=max(0, start), end=max(start, end), text=text))
                nominal_start += chunk_seconds
            if not segments:
                raise WhisperCppError("视频中未识别到足够的语音内容")
            language_label = ", ".join(languages) if languages else "unknown"
            progress(58, "GPU 语音转写完成")
            return Transcript(language=language_label, source="whisper_cpp", segments=segments)
        finally:
            self._stop_process(process)
            log_handle.close()
            for path in (chunk_path,):
                try:
                    path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _request_interruptibly(base_url: str, chunk_path: Path, process: subprocess.Popen, cancel_check: CancelCheck) -> dict:
        def request() -> dict:
            with chunk_path.open("rb") as audio:
                response = httpx.post(
                    f"{base_url}/inference",
                    files={"file": (chunk_path.name, audio, "audio/wav")},
                    data={
                        "language": "auto", "response_format": "verbose_json", "temperature": "0",
                        "temperature_inc": "0.2", "beam_size": "5", "best_of": "5",
                        "suppress_non_speech": "true", "no_language_probabilities": "true",
                    },
                    timeout=600,
                )
                response.raise_for_status()
                return json.loads(response.content.decode("utf-8", errors="replace"))

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper-request") as executor:
            future: Future[dict] = executor.submit(request)
            while not future.done():
                try:
                    cancel_check()
                except Exception:
                    WhisperCppTranscriber._stop_process(process)
                    raise
                time.sleep(0.2)
            try:
                return future.result()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                raise WhisperCppError(f"Whisper Vulkan 转写请求失败：{exc}") from exc

    @staticmethod
    def _stop_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
