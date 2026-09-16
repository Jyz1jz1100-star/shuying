"""Normalize public-service links to known single-video routes, never arbitrary URLs."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from .security import UnsafeUrlError, validate_public_url


def normalize_video_link(value: str, *, resolve_short: bool = True) -> str:
    links = re.findall(r'https?://[^\s<>"\u3000]+', value.strip(), flags=re.I)
    if len(links) != 1:
        raise UnsafeUrlError('请粘贴一个 B站或 YouTube 视频链接，可以包含分享文字')
    url = links[0].rstrip('。，、；！？”）)]}')
    try:
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            raise ValueError()
    except ValueError:
        raise UnsafeUrlError('视频链接格式无效') from None
    host = (parsed.hostname or '').lower()
    query = parse_qs(parsed.query)
    if host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}:
        if host == 'youtu.be':
            video_id = parsed.path.strip('/')
        elif parsed.path == '/watch':
            video_id = query.get('v', [''])[0]
        else:
            match = re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?', parsed.path)
            video_id = match[1] if match else ''
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise UnsafeUrlError('请使用单个 YouTube 视频链接，不支持频道或播放列表')
        canonical = 'https://www.youtube.com/watch?v=' + video_id
    elif host in {'bilibili.com', 'www.bilibili.com', 'm.bilibili.com'}:
        match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10}|av[0-9]+)/?', parsed.path)
        if not match:
            raise UnsafeUrlError('请使用 B站单个视频链接，不支持主页、直播或合集页')
        canonical = 'https://www.bilibili.com/video/' + match[1]
        part = query.get('p', ['1'])[0]
        if not part.isdigit() or not 1 <= int(part) <= 10000:
            raise UnsafeUrlError('分P编号无效')
        if int(part) > 1:
            canonical += '?p=' + str(int(part))
    elif host == 'b23.tv' and resolve_short and re.fullmatch(r'/[A-Za-z0-9]{1,32}/?', parsed.path):
        short_url = 'https://b23.tv' + parsed.path
        validate_public_url(short_url)
        try:
            # Only read response headers. Never follow a redirect before validating it.
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                with client.stream('GET', short_url) as response:
                    if response.status_code not in {301, 302, 303, 307, 308} or not response.headers.get('location'):
                        raise UnsafeUrlError('短链接暂时无法展开，请复制视频完整网址')
                    target = urljoin(short_url, response.headers['location'])
            return normalize_video_link(target, resolve_short=False)
        except httpx.HTTPError:
            raise UnsafeUrlError('短链接暂时无法展开，请复制视频完整网址') from None
    else:
        raise UnsafeUrlError('目前支持 B站和 YouTube 的公开视频链接，其他内容请上传文件')
    return validate_public_url(canonical)
