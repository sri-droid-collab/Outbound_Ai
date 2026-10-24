import httpx

from app.ai.tools.lead_research.page_fetcher import PageFetcher
from app.ai.tools.lead_research.site_crawler import crawl_site, pick_pages


async def _allow(url: str) -> None:
    return None


def _fetcher(handler) -> PageFetcher:
    return PageFetcher(
        user_agent="OutboundAI-LeadResearch/1.0",
        timeout=2.0,
        transport=httpx.MockTransport(handler),
        url_check=_allow,
    )


def _page(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html"})


HOME = """
<html><head><title>Acme</title><meta name="description" content="Robots for warehouses"></head><body>
<a href="/about-us">About</a> <a href="/services/automation">Services</a> <a href="/careers">Careers</a>
<a href="/blog/post-1">Blog</a> <a href="/brochure.pdf">About brochure</a>
<a href="https://other-site.com/about">Partner</a> <a href="/">Home</a>
</body></html>
"""


def test_pick_pages_prefers_relevant_same_site_links():
    links = [
        ("https://acme.com/blog/post-1", "Blog"),
        ("https://acme.com/about-us", "About"),
        ("https://acme.com/careers?utm=x", "Join us"),
        ("https://other-site.com/about", "Partner"),
        ("https://acme.com/brochure.pdf", "About brochure"),
        ("https://acme.com/", "Home"),
        ("https://www.acme.com/services/automation", "Services"),
    ]

    picked = pick_pages(links, "https://acme.com/", limit=3)

    assert set(picked) == {
        "https://acme.com/about-us",
        "https://acme.com/careers",
        "https://www.acme.com/services/automation",
    }


def test_pick_pages_respects_limit_and_dedupes():
    links = [("https://acme.com/about", "About")] * 3 + [("https://acme.com/careers/jobs", "Open jobs")]

    # "careers" + "jobs" both match, so it outranks the plain "about" page
    assert pick_pages(links, "https://acme.com/", limit=1) == ["https://acme.com/careers/jobs"]
    assert len(pick_pages(links, "https://acme.com/", limit=5)) == 2


async def test_crawl_reads_homepage_and_linked_pages():
    def handler(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/":
            return _page(HOME)
        return _page(f"<title>{path}</title><p>content of {path}</p>")

    async with _fetcher(handler) as fetcher:
        result = await crawl_site("https://acme.com/", fetcher, max_pages=4)

    urls = [p.url for p in result.pages]
    assert urls[0] == "https://acme.com/"
    assert result.pages[0].description == "Robots for warehouses"
    assert set(urls[1:]) == {
        "https://acme.com/about-us",
        "https://acme.com/services/automation",
        "https://acme.com/careers",
    }
    assert result.gaps == []


async def test_failed_subpage_becomes_a_gap_not_an_error():
    def handler(request):
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/":
            return _page(HOME)
        if path == "/careers":
            return httpx.Response(500, text="oops", headers={"content-type": "text/html"})
        return _page("<p>ok</p>")

    async with _fetcher(handler) as fetcher:
        result = await crawl_site("https://acme.com/", fetcher, max_pages=5)

    assert len(result.pages) >= 2
    assert any("/careers" in g and "http_500" in g for g in result.gaps)


async def test_unreadable_homepage_returns_empty_result_with_gap():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(503, text="down", headers={"content-type": "text/html"})

    async with _fetcher(handler) as fetcher:
        result = await crawl_site("https://acme.com/", fetcher, max_pages=5)

    assert result.pages == []
    assert result.gaps == ["Homepage could not be read (http_503)"]
