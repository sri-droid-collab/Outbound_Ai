"""SSRF guard for the lead-research crawler.

The sites it fetches come from user-entered data (contact.website), so every
URL - including each redirect hop - must resolve only to public addresses.
Loopback, private ranges, link-local (cloud metadata at 169.254.169.254) and
internal hostnames are refused.

Residual risk: the address is validated here and httpx resolves it again when
connecting, so a hostile DNS server could answer differently the second time
(DNS rebinding). Closing that needs pinning the connection to the validated
IP; revisit if the crawler is ever exposed to untrusted users.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_PORTS = {None, 80, 443}


class UnsafeUrlError(ValueError):
    """The URL points somewhere the crawler must not go."""


class UnresolvableHostError(UnsafeUrlError):
    """The hostname doesn't exist in DNS - a typo, not an attack."""


def normalize_website(raw: str) -> str | None:
    """'Acme.com/about?x=1' -> 'https://acme.com'. None when it can't be a public website."""
    s = (raw or "").strip()
    if not s or len(s) > 2000 or any(c.isspace() for c in s):
        return None
    if "://" not in s:
        s = "https://" + s
    try:
        parts = urlsplit(s)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host or port not in ALLOWED_PORTS:
        return None
    # Single-label names ("localhost", "intranet") are never a company website.
    if "." not in host and ":" not in host:
        return None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _is_public(str(literal)):
        return None
    return f"{parts.scheme}://{host}"


def site_domain(website: str) -> str:
    """Host without a leading 'www.', for DNS lookups and display."""
    host = urlsplit(website).hostname or ""
    return host.removeprefix("www.")


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


async def assert_public_url(url: str) -> None:
    """Raise UnsafeUrlError unless `url` is http(s) on an allowed port and every
    address its host resolves to is public."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise UnsafeUrlError("malformed url") from e
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or port not in ALLOWED_PORTS:
        raise UnsafeUrlError("scheme, host or port not allowed")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(str(literal)):
            raise UnsafeUrlError("non-public address")
        return

    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as e:
        raise UnresolvableHostError("host does not resolve") from e
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_is_public(a) for a in addresses):
        raise UnsafeUrlError("non-public address")
