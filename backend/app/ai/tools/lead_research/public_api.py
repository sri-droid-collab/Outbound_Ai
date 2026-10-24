"""HTTP client for the handful of fixed public data sources (news feeds, Wikidata).

Unlike the page fetcher, the URLs here are ours, not user-supplied, so there is no SSRF
surface - but the host allowlist keeps it that way if someone later passes a URL through.
Every failure becomes `SourceUnavailable` with a short reason, so a flaky free source
degrades to a gap in the brief instead of failing the run.
"""

import json

import httpx

MAX_BYTES = 2_000_000


class SourceUnavailable(Exception):
    """The source couldn't be read right now. The message is a short code safe to show."""


class PublicApiClient:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float,
        allowed_hosts: set[str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allowed_hosts = allowed_hosts
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": user_agent},
            follow_redirects=False,
        )

    async def __aenter__(self) -> "PublicApiClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def get_text(self, url: str, params: dict | None = None) -> str:
        if httpx.URL(url).host not in self._allowed_hosts:
            raise SourceUnavailable("host_not_allowed")
        try:
            async with self._client.stream("GET", url, params=params) as resp:
                if resp.status_code == 429:
                    raise SourceUnavailable("rate_limited")
                if not 200 <= resp.status_code < 300:  # includes redirects, which are never followed
                    raise SourceUnavailable(f"http_{resp.status_code}")
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise SourceUnavailable("too_large")
                    chunks.append(chunk)
        except httpx.TimeoutException as e:
            raise SourceUnavailable("timeout") from e
        except httpx.HTTPError as e:
            raise SourceUnavailable("network_error") from e
        return b"".join(chunks).decode(resp.charset_encoding or "utf-8", errors="replace")

    async def get_json(self, url: str, params: dict | None = None) -> dict:
        text = await self.get_text(url, params)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise SourceUnavailable("bad_response") from e
        if not isinstance(data, dict):
            raise SourceUnavailable("bad_response")
        return data
