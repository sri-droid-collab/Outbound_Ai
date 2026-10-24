from urllib.parse import urlsplit

import httpx

from app.ai.tools.lead_research.page_fetcher import MAX_BYTES, PageFetcher
from app.ai.tools.lead_research.url_safety import assert_public_url


async def _check_literal_ips_only(url: str) -> None:
    """Test double for the DNS-resolving check: hostnames pass, IP literals get the real guard."""
    host = urlsplit(url).hostname or ""
    if host[:1].isdigit() or ":" in host:
        await assert_public_url(url)


def _fetcher(handler) -> PageFetcher:
    return PageFetcher(
        user_agent="OutboundAI-LeadResearch/1.0",
        timeout=2.0,
        transport=httpx.MockTransport(handler),
        url_check=_check_literal_ips_only,
    )


def _html(body: str = "<p>hello</p>", status: int = 200, content_type: str = "text/html; charset=utf-8"):
    return httpx.Response(status, text=body, headers={"content-type": content_type})


async def test_fetches_html_page():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return _html("<p>Acme builds robots</p>")

    async with _fetcher(handler) as fetcher:
        result = await fetcher.fetch("https://acme.com/")

    assert result.ok
    assert "Acme builds robots" in result.text
    assert result.final_url == "https://acme.com/"


async def test_follows_redirects_and_reports_final_url():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "acme.com":
            return httpx.Response(301, headers={"location": "https://www.acme.com/home"})
        return _html("<p>moved</p>")

    async with _fetcher(handler) as fetcher:
        result = await fetcher.fetch("https://acme.com/")

    assert result.ok
    assert result.final_url == "https://www.acme.com/home"


async def test_redirect_to_internal_address_is_blocked():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    async with _fetcher(handler) as fetcher:
        result = await fetcher.fetch("https://acme.com/")

    assert result.error == "unsafe_address"
    assert not any("169.254.169.254" in u for u in seen)  # the metadata address was never requested


async def test_direct_internal_target_is_blocked_without_a_request():
    def handler(request):
        raise AssertionError("no request should be made")

    async with _fetcher(handler) as fetcher:
        result = await fetcher.fetch("http://127.0.0.1:80/admin")

    assert result.error == "unsafe_address"


async def test_robots_disallow_is_honoured():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nDisallow: /private\n", headers={"content-type": "text/plain"}
            )
        raise AssertionError("a disallowed page must not be requested")

    async with _fetcher(handler) as fetcher:
        result = await fetcher.fetch("https://acme.com/private/team")

    assert result.error == "blocked_by_robots"


async def test_robots_rule_for_our_agent_applies():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: OutboundAI-LeadResearch\nDisallow: /\n",
                headers={"content-type": "text/plain"},
            )
        raise AssertionError("must not fetch")

    async with _fetcher(handler) as fetcher:
        assert (await fetcher.fetch("https://acme.com/")).error == "blocked_by_robots"


async def test_missing_or_broken_robots_means_allowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(500)
        return _html("<p>ok</p>")

    async with _fetcher(handler) as fetcher:
        assert (await fetcher.fetch("https://acme.com/")).ok


async def test_robots_is_fetched_once_per_origin():
    robots_hits = []

    def handler(request):
        if request.url.path == "/robots.txt":
            robots_hits.append(1)
            return httpx.Response(404)
        return _html()

    async with _fetcher(handler) as fetcher:
        await fetcher.fetch("https://acme.com/a")
        await fetcher.fetch("https://acme.com/b")

    assert len(robots_hits) == 1


async def test_non_html_content_is_rejected():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})

    async with _fetcher(handler) as fetcher:
        assert (await fetcher.fetch("https://acme.com/brochure")).error == "not_html"


async def test_http_error_status_is_reported():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(403, text="nope", headers={"content-type": "text/html"})

    async with _fetcher(handler) as fetcher:
        assert (await fetcher.fetch("https://acme.com/")).error == "http_403"


async def test_oversized_response_is_truncated_not_fully_read():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return _html("x" * (MAX_BYTES * 3))

    async with _fetcher(handler) as fetcher:
        result = await fetcher.fetch("https://acme.com/")

    assert result.ok
    assert len(result.text) <= MAX_BYTES


async def test_redirect_loop_gives_up():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://acme.com/again"})

    async with _fetcher(handler) as fetcher:
        assert (await fetcher.fetch("https://acme.com/")).error == "too_many_redirects"


async def test_network_failure_is_a_result_not_an_exception():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ConnectError("boom")

    async with _fetcher(handler) as fetcher:
        assert (await fetcher.fetch("https://acme.com/")).error == "network_error"


async def test_nonexistent_domain_is_reported_as_host_not_found():
    from app.ai.tools.lead_research.url_safety import UnresolvableHostError

    async def check(url):
        raise UnresolvableHostError("host does not resolve")

    def handler(request):
        raise AssertionError("no request should be made")

    fetcher = PageFetcher(
        user_agent="OutboundAI-LeadResearch/1.0",
        timeout=2.0,
        transport=httpx.MockTransport(handler),
        url_check=check,
    )
    async with fetcher:
        assert (await fetcher.fetch("https://no-such-company.test/")).error == "host_not_found"
