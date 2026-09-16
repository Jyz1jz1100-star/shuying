from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    pass


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("仅支持 HTTP 或 HTTPS 视频链接")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrlError("视频链接格式无效")
    host = parsed.hostname.rstrip(".")
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise UnsafeUrlError("不允许访问本机或局域网地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise UnsafeUrlError("无法解析视频地址") from exc
    if not addresses:
        raise UnsafeUrlError("无法解析视频地址")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise UnsafeUrlError("不允许访问本机、局域网或保留地址")
    return url
