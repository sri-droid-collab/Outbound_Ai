"""Polite, SSRF-safe page fetching for lead research.

Every hop (including redirects) is checked by `assert_public_url`, responses
are size-capped, robots.txt is honoured, and a failure is a result rather than
an exception - a flaky site must never stop a research run.
"""

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.ai.tools.lead_research.url_safety import UnresolvableHostError, UnsafeUrlError, assert_public_url

logger = logging.getLogger(__name__)

MAX_BYTES = 1_500_000
MAX_REDIRECTS = 4
HTML_TYPES = ("text/html", "application/xhtml")


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    text: str = ""
    error: str = ""  # short code, safe to show: blocked_by_robots, unsafe_address, timeout, ...

    @property
    def ok(self) -> bool:
        return not self.error


class PageFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        url_check=assert_public_url,
    ) -> None:
        self._ua_token = user_agent.split("/", 1)[0]
        self._timeout = timeout
        self._url_check = url_check
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=False,
        )
        self._robots: dict[str, RobotFileParser | None] = {}

    async def __aenter__(self) -> "PageFetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        """Fetch an HTML page. Never raises (other than cancellation)."""
        try:
            if not await self._allowed_by_robots(url):
                return FetchResult(url, error="blocked_by_robots")
            # Per-chunk read timeouts don't stop a slow-drip response, so bound the whole fetch.
            body = await asyncio.wait_for(self._get(url, HTML_TYPES), self._timeout * 2)
        except UnresolvableHostError:
            return FetchResult(url, error="host_not_found")
        except UnsafeUrlError:
            return FetchResult(url, error="unsafe_address")
        except asyncio.TimeoutError:
            return FetchResult(url, error="timeout")
        except httpx.HTTPError as e:
            logger.info(
                f"[LEAD-RESEARCH] fetch failed host={urlsplit(url).hostname} error={type(e).__name__}"
            )
            return FetchResult(url, error="network_error")
        if isinstance(body, str):
            return FetchResult(url, error=body)
        text, final_url = body
        return FetchResult(url, final_url=final_url, text=text)

    async def _get(self, url: str, accept: tuple[str, ...]) -> tuple[str, str] | str:
        """Returns (text, final_url) or a short error code string."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            await self._url_check(current)
            async with self._client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return "bad_redirect"
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    return f"http_{resp.status_code}"
                content_type = resp.headers.get("content-type", "").lower()
                if not any(t in content_type for t in accept):
                    return "not_html"
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    chunks.append(chunk)
                    if size >= MAX_BYTES:
                        break  # a truncated page still has its useful text near the top
                raw = b"".join(chunks)[:MAX_BYTES]
                try:
                    return raw.decode(resp.charset_encoding or "utf-8", errors="replace"), current
                except LookupError:
                    return raw.decode("utf-8", errors="replace"), current
        return "too_many_redirects"

    async def _allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = await self._load_robots(origin)
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self._ua_token, url)

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        """None means "no usable robots.txt" - treated as allow-all, per the
        usual convention when the file is missing or unreachable."""
        try:
            body = await asyncio.wait_for(
                self._get(f"{origin}/robots.txt", ("text/plain", "text/html")), self._timeout
            )
        except (UnsafeUrlError, asyncio.TimeoutError, httpx.HTTPError):
            return None
        if isinstance(body, str):
            return None
        parser = RobotFileParser()
        parser.parse(body[0].splitlines())
        return parser
