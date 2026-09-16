"""Atomic JSON checkpoint storage for the video summarizer.

The module is standard-library only so both the FastAPI service and offline
tooling can import it.  Documents are written through a unique temporary file
plus ``os.replace`` so a crash or a full disk never leaves a half-written
checkpoint behind.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_NAME_PATTERN = re.compile(r"[a-zA-Z0-9_-]+")
_READ_CHUNK_BYTES = 1024 * 1024


class UnsafeCheckpointName(ValueError):
    """Raised when a checkpoint name could escape the storage root."""


def _canonical_bytes(value: Any) -> bytes:
    """Encode ``value`` as canonical (sorted, compact) UTF-8 JSON."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _checked_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name):
        raise UnsafeCheckpointName("checkpoint name must match [a-zA-Z0-9_-]+")
    return name


def _read_document(path: Path) -> dict | None:
    """Return the parsed JSON object at ``path`` or None when unusable."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        document = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    return document


def atomic_json(path: Path, value: Any) -> None:
    """Write ``value`` as canonical JSON to ``path`` atomically.

    The payload is written to a unique temporary file next to the target,
    flushed and fsynced, then moved over the destination with ``os.replace``.
    On any failure the previous file is preserved and the temporary file is
    removed.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(value)

    open_fd: int | None = None
    temp_path: Path | None = None
    try:
        open_fd, raw_temp = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        temp_path = Path(raw_temp)
        with os.fdopen(open_fd, "wb") as handle:
            open_fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if open_fd is not None:
            try:
                os.close(open_fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def fingerprint(value: Any) -> str:
    """Return the SHA-256 of the canonical JSON encoding of ``value``."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def file_fingerprint(path: Path) -> str:
    """Return the streaming SHA-256 of the bytes stored at ``path``."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(_READ_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


class Checkpoints:
    """Small ``root/<name>.json`` store of resumable job checkpoints."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, name: str) -> Path:
        """Return the storage path for ``name``, rejecting unsafe names."""
        _checked_name(name)
        return self.root / f"{name}.json"

    def load(self, name: str, key: str) -> Any | None:
        """Return the stored payload or None when missing, corrupt or foreign."""
        document = _read_document(self.path_for(name))
        if document is None or document.get("version") != SCHEMA_VERSION:
            return None
        stored_key = document.get("key")
        if not isinstance(stored_key, str) or stored_key != key:
            return None
        if "payload" not in document:
            return None
        if document.get("checksum") != fingerprint(document["payload"]):
            return None
        return document["payload"]

    def save(self, name: str, key: str, value: Any) -> None:
        """Atomically store ``value`` under ``name`` and ``key``."""
        document = {
            "version": SCHEMA_VERSION,
            "key": key,
            "checksum": fingerprint(value),
            "updated_at": _utc_now(),
            "payload": value,
        }
        atomic_json(self.path_for(name), document)

    def status(self) -> list[dict]:
        """Return ``[{name, key, updated_at}]`` for valid documents, sorted."""
        entries: list[dict] = []
        for path in self.root.glob("*.json"):
            name = path.stem
            if not _NAME_PATTERN.fullmatch(name):
                continue
            document = _read_document(path)
            if document is None or document.get("version") != SCHEMA_VERSION:
                continue
            key = document.get("key")
            if not isinstance(key, str) or "payload" not in document:
                continue
            if document.get("checksum") != fingerprint(document["payload"]):
                continue
            updated_at = document.get("updated_at")
            entries.append(
                {
                    "name": name,
                    "key": key,
                    "updated_at": updated_at if isinstance(updated_at, str) else "",
                }
            )
        entries.sort(key=lambda entry: (entry["name"], entry["key"]))
        return entries
