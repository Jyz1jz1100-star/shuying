from __future__ import annotations

import socket
import pytest
from videosummarizer.security import UnsafeUrlError, validate_public_url


def test_rejects_non_http_and_credentials():
    with pytest.raises(UnsafeUrlError): validate_public_url("file:///c:/secret.mp4")
    with pytest.raises(UnsafeUrlError): validate_public_url("https://user:pass@example.com/video")


def test_rejects_private_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(UnsafeUrlError): validate_public_url("https://example.test/video")


def test_accepts_public_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    assert validate_public_url("https://example.com/video") == "https://example.com/video"
