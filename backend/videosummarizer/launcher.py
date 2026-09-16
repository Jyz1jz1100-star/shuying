from __future__ import annotations

import multiprocessing
import logging
from logging.handlers import RotatingFileHandler
import socket
import subprocess
import sys
import threading
import webbrowser

import uvicorn

from videosummarizer.app import app
from videosummarizer.config import settings


def configure_logging() -> logging.Logger:
    settings.ensure_directories()
    log_path = settings.data_dir / "VideoSummarizer.log"
    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return logging.getLogger("videosummarizer.launcher")


def show_fatal_error(message: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "述影启动失败", 0x10)


def choose_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((settings.host, port))
                return port
            except OSError:
                continue
    raise RuntimeError("本机端口被占用，无法启动述影")


def main() -> None:
    multiprocessing.freeze_support()
    if "--self-test" in sys.argv:
        from importlib.metadata import version

        import av
        import pyaudiowpatch as pyaudio
        import srt
        import yt_dlp
        from docx import Document

        whisper_exe = settings.whisper_runtime_dir / "whisper-cli.exe"
        result = subprocess.run(
            [str(whisper_exe), "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or b"Vulkan" not in result.stdout:
            raise RuntimeError("Whisper Vulkan runtime self-test failed")
        with pyaudio.PyAudio() as audio:
            if not list(audio.get_loopback_device_info_generator()):
                raise RuntimeError("Windows WASAPI loopback self-test failed")
        versions = {
            "av": av.__version__, "whisper_cpp": "v1.8.4 Vulkan", "audio": "WASAPI loopback", "subtitle": version("srt"),
            "yt_dlp": yt_dlp.version.__version__, "python_docx": Document.__module__,
        }
        print("SELF_TEST_OK", versions)
        return
    logger = configure_logging()
    try:
        port = choose_port(settings.port)
        url = f"http://{settings.host}:{port}/"
        # Windowed PyInstaller executables have no stdout/stderr streams. Disable
        # Uvicorn's console formatter and keep diagnostics in our rotating file log.
        config = uvicorn.Config(app, host=settings.host, port=port, log_level="warning", log_config=None, access_log=False)
        server = uvicorn.Server(config)
        app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
        logger.info("述影启动：%s", url)
        threading.Timer(1.1, lambda: webbrowser.open(url)).start()
        server.run()
        logger.info("述影已退出")
    except Exception as exc:
        logger.exception("述影启动失败")
        show_fatal_error(f"述影无法启动：{exc}\n\n日志：{settings.data_dir / 'VideoSummarizer.log'}")
        raise


if __name__ == "__main__":
    main()
