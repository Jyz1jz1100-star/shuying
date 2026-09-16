import socket

import httpx
import pytest

from videosummarizer.security import UnsafeUrlError
from videosummarizer.video_links import normalize_video_link


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))])


@pytest.mark.parametrize('value,expected', [
    ('分享：https://b23.tv/abc123', None),
    ('看看这个 https://www.bilibili.com/video/BV1xx411c7mD/?p=2&share_source=copy。', 'https://www.bilibili.com/video/BV1xx411c7mD?p=2'),
    ('https://youtu.be/BaW_jenozKc?t=5', 'https://www.youtube.com/watch?v=BaW_jenozKc'),
    ('https://m.youtube.com/shorts/BaW_jenozKc', 'https://www.youtube.com/watch?v=BaW_jenozKc'),
])
def test_canonical_links(value, expected, monkeypatch):
    if expected is None:
        original = httpx.Client
        def handle(request):
            assert request.url.host == 'b23.tv'
            return httpx.Response(302, headers={'Location': 'https://www.bilibili.com/video/BV1xx411c7mD'})
        monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
        expected = 'https://www.bilibili.com/video/BV1xx411c7mD'
    assert normalize_video_link(value) == expected


@pytest.mark.parametrize('url', [
    'http://127.0.0.1/a', 'https://youtube.com.evil.example/watch?v=BaW_jenozKc',
    'https://youtube.com@localhost/watch?v=BaW_jenozKc', 'file:///etc/passwd',
    'https://www.youtube.com/redirect?q=http://127.0.0.1/',
    'https://www.youtube.com/playlist?list=123', 'https://bilibili.com/video/BV1xx411c7mD?p=-1',
    'https://www.youtube.com:8765/watch?v=BaW_jenozKc',
    'https://bilibili.com/video/BV1xx411c7mD https://youtu.be/BaW_jenozKc',
])
def test_reject_arbitrary_routes(url):
    with pytest.raises(UnsafeUrlError):
        normalize_video_link(url)


def test_private_dns_and_short_link_redirect_are_rejected(monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'})), **kwargs))
    with pytest.raises(UnsafeUrlError):
        normalize_video_link('https://b23.tv/abc')
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('192.168.1.1', 443))])
    with pytest.raises(UnsafeUrlError):
        normalize_video_link('https://youtu.be/BaW_jenozKc')
