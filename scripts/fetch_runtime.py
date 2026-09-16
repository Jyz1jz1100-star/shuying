#!/usr/bin/env python3
"""Fetch/install the pinned whisper.cpp Vulkan runtime for Windows.

This is a stdlib-only, no-credentials helper. The downloaded archive is
pinned by SHA-256 from THIRD_PARTY_NOTICES.md. Redistributors of the extracted
binaries must include the upstream whisper.cpp MIT license and
THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "vendor" / "whispercpp" / "runtime"
CACHE_DIR = REPO_ROOT / "vendor" / "whispercpp"
ARCHIVE_NAME = "whisper-v1.8.4-windows-vulkan-x64.zip"
ARCHIVE_URL = (
    "https://github.com/lemonade-sdk/whisper.cpp-rocm/releases/download/"
    f"v1.8.4/{ARCHIVE_NAME}"
)
ARCHIVE_SHA256 = "e0d20a0f92e31b98adc0faf71172efc810b701e6391a9d858ca045bff26f77cd"
CACHED_ARCHIVE = CACHE_DIR / ARCHIVE_NAME
SERVER_EXE = "whisper-server.exe"
NETWORK_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK = 1024 * 1024


class FetchError(RuntimeError):
    """Raised when the runtime cannot be verified or installed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(path: Path) -> None:
    if not path.is_file():
        raise FetchError(f"archive not found: {path}")
    actual = sha256_file(path)
    if actual.lower() != ARCHIVE_SHA256:
        raise FetchError(
            f"archive SHA-256 mismatch for {path}: "
            f"expected {ARCHIVE_SHA256}, got {actual}"
        )


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def download_archive() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        ARCHIVE_URL,
        headers={"User-Agent": "video-summarizer-fetch-runtime/1.0"},
    )
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{ARCHIVE_NAME}.",
        suffix=".part",
        dir=str(CACHE_DIR),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("wb") as out:
            try:
                with urllib.request.urlopen(
                    request, timeout=NETWORK_TIMEOUT_SECONDS
                ) as response:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise FetchError(
                    f"failed to download {ARCHIVE_URL}: {exc}"
                ) from exc
        verify_archive(tmp_path)
        os.replace(tmp_path, CACHED_ARCHIVE)
    except FetchError:
        _remove_quietly(tmp_path)
        raise
    except Exception as exc:
        _remove_quietly(tmp_path)
        raise FetchError(
            f"failed to cache archive {ARCHIVE_NAME}: {exc}"
        ) from exc


def _safe_zip_path(name: str) -> PurePosixPath:
    if not name:
        raise FetchError("zip contains an empty path")
    if "\\" in name:
        raise FetchError(f"zip contains a backslash path: {name!r}")
    if ":" in name:
        raise FetchError(f"zip contains a drive/ADS path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise FetchError(f"zip contains an absolute path: {name!r}")
    if path == PurePosixPath("."):
        raise FetchError(f"zip contains an empty path: {name!r}")
    for part in path.parts:
        if part in ("", ".", ".."):
            raise FetchError(f"zip contains a traversal path: {name!r}")
    return path


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return stat.S_ISLNK(mode)


def _validate_zip(zf: zipfile.ZipFile) -> None:
    for info in zf.infolist():
        if info.flag_bits & 0x1:
            raise FetchError(f"zip member is encrypted: {info.filename!r}")
        _safe_zip_path(info.filename)
        if _zip_member_is_symlink(info):
            raise FetchError(f"zip contains a symlink: {info.filename!r}")
        mode = (info.external_attr >> 16) & 0o170000
        if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise FetchError(
                f"zip contains a non-regular file: {info.filename!r}"
            )


def _find_server(zf: zipfile.ZipFile) -> tuple[PurePosixPath, PurePosixPath]:
    matches: list[PurePosixPath] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = _safe_zip_path(info.filename)
        if path.name.lower() == SERVER_EXE.lower():
            matches.append(path)
    if not matches:
        raise FetchError(f"zip does not contain {SERVER_EXE}")
    if len(matches) > 1:
        joined = ", ".join(str(path) for path in matches)
        raise FetchError(
            f"zip contains multiple {SERVER_EXE} files: {joined}"
        )
    server_path = matches[0]
    return server_path, server_path.parent


def _relative_to_prefix(path: PurePosixPath, prefix: PurePosixPath) -> PurePosixPath:
    if not prefix.parts:
        return path
    return path.relative_to(prefix)


def verify_runtime(runtime_dir: Path) -> None:
    if not runtime_dir.is_dir():
        raise FetchError(f"runtime directory not found: {runtime_dir}")
    exe = runtime_dir / SERVER_EXE
    if not exe.is_file():
        raise FetchError(f"missing required runtime executable: {exe}")
    if exe.is_symlink():
        raise FetchError(f"runtime executable is a symlink: {exe}")
    for filename in ['whisper-cli.exe', 'whisper.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-cpu.dll', 'ggml-vulkan.dll']:
        if not (runtime_dir / filename).is_file():
            raise FetchError(f'missing runtime component: {filename}')
    dlls = sorted(
        path for path in runtime_dir.glob("*.dll") if path.is_file()
    )
    if not dlls:
        raise FetchError(
            f"no DLL files found in runtime directory: {runtime_dir}"
        )


def extract_archive(archive: Path, staging_dir: Path) -> None:
    staging_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        _validate_zip(zf)
        server_path, prefix = _find_server(zf)
        for info in zf.infolist():
            path = _safe_zip_path(info.filename)
            if path != server_path and prefix not in path.parents:
                continue
            relative = _relative_to_prefix(path, prefix)
            target = staging_dir / Path(*relative.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    verify_runtime(staging_dir)


def install_runtime(staging_dir: Path) -> None:
    RUNTIME_DIR.parent.mkdir(parents=True, exist_ok=True)
    if RUNTIME_DIR.exists():
        raise FetchError(
            f"refusing to replace existing runtime directory: {RUNTIME_DIR}. "
            "Remove it manually before re-staging."
        )
    try:
        os.replace(staging_dir, RUNTIME_DIR)
    except OSError as exc:
        raise FetchError(
            f"failed to install runtime into {RUNTIME_DIR}: {exc}"
        ) from exc


def ensure_archive() -> Path:
    if CACHED_ARCHIVE.is_file():
        try:
            verify_archive(CACHED_ARCHIVE)
            return CACHED_ARCHIVE
        except FetchError:
            pass
    download_archive()
    verify_archive(CACHED_ARCHIVE)
    return CACHED_ARCHIVE


def run_default() -> None:
    archive = ensure_archive()
    if RUNTIME_DIR.exists():
        try:
            verify_runtime(RUNTIME_DIR)
        except FetchError as exc:
            raise FetchError(
                f"{exc}; refusing to restage because {RUNTIME_DIR} "
                "already exists. Remove it manually to re-fetch."
            ) from exc
        print(f"runtime already present and verified: {RUNTIME_DIR}")
        return

    RUNTIME_DIR.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=".runtime-staging-",
            dir=str(RUNTIME_DIR.parent),
        )
    )
    try:
        extract_archive(archive, staging)
        install_runtime(staging)
    except FetchError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise FetchError(f"failed to stage runtime: {exc}") from exc
    print(f"installed runtime: {RUNTIME_DIR}")


def run_verify_only() -> None:
    verify_runtime(RUNTIME_DIR)
    print(f"runtime verified: {RUNTIME_DIR}")
    if CACHED_ARCHIVE.is_file():
        verify_archive(CACHED_ARCHIVE)
        print(f"cached archive verified: {CACHED_ARCHIVE}")
    else:
        print(
            f"cached archive not present; hash not checked: {CACHED_ARCHIVE}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch/install the pinned whisper.cpp Vulkan runtime "
            "(v1.8.4 Windows x64)."
        )
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify the installed runtime and cached archive; do not download",
    )
    args = parser.parse_args(argv)
    try:
        if args.verify_only:
            run_verify_only()
        else:
            run_default()
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
