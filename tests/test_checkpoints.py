from __future__ import annotations

import hashlib
import json

import pytest

from videosummarizer import checkpoints
from videosummarizer.checkpoints import Checkpoints, atomic_json, file_fingerprint, fingerprint


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_save_load_roundtrip_writes_schema_document(tmp_path):
    store = Checkpoints(tmp_path / "store")
    value = {"status": "running", "stage": "transcribe", "percent": 42, "items": [1, 2, 3]}

    store.save("job-1", "session", value)

    path = store.root / "job-1.json"
    document = _read_json(path)
    assert document["version"] == 1
    assert document["key"] == "session"
    assert document["checksum"] == fingerprint(value)
    assert document["payload"] == value
    assert isinstance(document["updated_at"], str) and document["updated_at"]
    assert store.load("job-1", "session") == value


def test_constructor_creates_root(tmp_path):
    store = Checkpoints(tmp_path / "missing" / "deep")
    assert store.root.is_dir()
    assert store.status() == []


def test_load_missing_file_returns_none(tmp_path):
    store = Checkpoints(tmp_path / "store")
    assert store.load("absent", "key") is None


def test_load_rejects_mismatched_key(tmp_path):
    store = Checkpoints(tmp_path / "store")
    store.save("job", "session-a", {"n": 1})

    assert store.load("job", "session-b") is None
    assert store.load("job", "session-a") == {"n": 1}


def test_load_rejects_wrong_schema_version(tmp_path):
    store = Checkpoints(tmp_path / "store")
    store.save("job", "key", {"n": 1})

    document = _read_json(store.root / "job.json")
    document["version"] = 2
    atomic_json(store.root / "job.json", document)

    assert store.load("job", "key") is None


def test_load_rejects_corrupt_payload(tmp_path):
    store = Checkpoints(tmp_path / "store")
    store.save("job", "key", {"n": 1})
    path = store.root / "job.json"

    document = _read_json(path)
    document["payload"] = {"n": 2}
    atomic_json(path, document)
    assert store.load("job", "key") is None

    document = _read_json(path)
    del document["payload"]
    del document["checksum"]
    atomic_json(path, document)
    assert store.load("job", "key") is None


def test_load_rejects_checksum_mismatch(tmp_path):
    store = Checkpoints(tmp_path / "store")
    store.save("job", "key", {"n": 1})
    path = store.root / "job.json"

    document = _read_json(path)
    document["checksum"] = "0" * 64
    atomic_json(path, document)
    assert store.load("job", "key") is None


def test_load_rejects_unparsable_document(tmp_path):
    store = Checkpoints(tmp_path / "store")
    path = store.root / "job.json"

    path.write_text("{ not json", encoding="utf-8")
    assert store.load("job", "key") is None

    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert store.load("job", "key") is None

    path.write_text("", encoding="utf-8")
    assert store.load("job", "key") is None


def test_save_overwrites_previous_value(tmp_path):
    store = Checkpoints(tmp_path / "store")
    store.save("job", "key", {"n": 1})
    store.save("job", "key", {"n": 2})

    assert store.load("job", "key") == {"n": 2}
    assert len(list(store.root.glob("*.json"))) == 1


def test_atomic_json_creates_parent_and_replaces(tmp_path):
    target = tmp_path / "nested" / "value.json"
    atomic_json(target, {"a": 1})
    assert _read_json(target) == {"a": 1}

    atomic_json(target, {"a": 2})
    assert _read_json(target) == {"a": 2}
    assert [item.name for item in target.parent.iterdir()] == ["value.json"]


def test_atomic_json_failure_preserves_previous_value(tmp_path, monkeypatch):
    store = Checkpoints(tmp_path / "store")
    store.save("job", "key", {"n": 1})

    def explode(*args, **kwargs):
        raise OSError("simulated disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(checkpoints.os, "replace", explode)
        with pytest.raises(OSError):
            store.save("job", "key", {"n": 2})

    assert store.load("job", "key") == {"n": 1}
    assert [item.name for item in store.root.iterdir()] == ["job.json"]


def test_atomic_json_unserializable_value_keeps_previous_file(tmp_path):
    target = tmp_path / "value.json"
    atomic_json(target, {"a": 1})

    with pytest.raises(TypeError):
        atomic_json(target, {"a": object()})

    assert _read_json(target) == {"a": 1}
    assert [item.name for item in tmp_path.iterdir()] == ["value.json"]


@pytest.mark.parametrize(
    "name", ["", ".", "..", "../evil", "..\\evil", "a/b", "a\\b", "a b", "job.json", "naïve", None]
)
def test_unsafe_names_are_rejected(tmp_path, name):
    store = Checkpoints(tmp_path / "store")

    with pytest.raises(ValueError):
        store.save(name, "key", {"n": 1})
    with pytest.raises(ValueError):
        store.load(name, "key")

    assert list(store.root.iterdir()) == []
    assert not (tmp_path / "evil.json").exists()


def test_safe_names_are_accepted(tmp_path):
    store = Checkpoints(tmp_path / "store")
    store.save("Job_1-2", "key", {"n": 1})
    assert store.load("Job_1-2", "key") == {"n": 1}
    assert store.path_for("Job_1-2") == store.root / "Job_1-2.json"


def test_fingerprint_is_canonical_json_sha256():
    assert fingerprint({"b": [2, 3], "a": 1}) == hashlib.sha256(b'{"a":1,"b":[2,3]}').hexdigest()
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})
    assert fingerprint({"s": ["中文"], "t": "视频"}) == fingerprint({"t": "视频", "s": ["中文"]})


def test_file_fingerprint_streams_file_contents(tmp_path):
    path = tmp_path / "blob.bin"
    data = bytes(range(256)) * 10_000
    path.write_bytes(data)

    assert file_fingerprint(path) == hashlib.sha256(data).hexdigest()


def test_status_lists_valid_items_sorted(tmp_path):
    store = Checkpoints(tmp_path / "store")
    store.save("b-job", "key", {"n": 1})
    store.save("a-job", "second", {"n": 2})
    store.save("a-job", "first", {"n": 3})

    status = store.status()
    assert [(item["name"], item["key"]) for item in status] == [
        ("a-job", "first"),
        ("b-job", "key"),
    ]
    assert all(set(item) == {"name", "key", "updated_at"} for item in status)
    assert all(isinstance(item["updated_at"], str) and item["updated_at"] for item in status)


def test_status_skips_corrupt_and_foreign_files(tmp_path):
    store = Checkpoints(tmp_path / "store")
    store.save("good", "key", {"n": 1})
    store.save("broken", "key", {"n": 1})

    (store.root / "broken.json").write_text("{ oops", encoding="utf-8")
    (store.root / "notes.txt").write_text("ignored", encoding="utf-8")
    (store.root / "weird name.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
    atomic_json(
        store.root / "old.json",
        {"version": 0, "key": "key", "checksum": fingerprint({}), "payload": {}},
    )

    assert [(item["name"], item["key"]) for item in store.status()] == [("good", "key")]
