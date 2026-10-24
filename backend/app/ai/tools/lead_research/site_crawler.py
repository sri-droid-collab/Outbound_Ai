"""Read a company's own site: the homepage plus the few pages most likely to
say what they do, how big they are and what they're hiring for."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit

from app.ai.tools.lead_research.html_text import extract_page
from app.ai.tools.lead_research.page_fetcher import FetchResult, PageFetcher

logger = logging.getLogger(__name__)

# (substring in path or anchor text, weight). Higher weight = fetched sooner.
PAGE_HINTS = [
    ("about", 5),
    ("service", 5),
    ("career", 5),
    ("solution", 4),
    ("company", 4),
    ("who-we-are", 4),
    ("job", 4),
    ("hiring", 4),
    ("vacanc", 4),
    ("opening", 4),
    ("work-with-us", 4),
    ("join", 3),
    ("product", 3),
    ("team", 3),
    ("leadership", 3),
    ("industr", 2),
    ("contact", 2),
    ("news", 2),
    ("press", 2),
]
_SKIP_EXTENSIONS = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|pptx?|mp[34]|css|js)$", re.I)
FETCH_CONCURRENCY = 2


@dataclass
class CrawledPage:
    url: str
    title: str
    description: str
    text: str
    fetched_at: datetime
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)


@dataclass
class CrawlResult:
    pages: list[CrawledPage] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    home_error: str = ""  # fetch error code when the homepage itself couldn't be read
    home_html: str = ""  # raw homepage source and headers, for technology detection
    home_headers: dict[str, str] = field(default_factory=dict)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


_CAREER_PATH_HINTS = ("career", "job", "join", "work-with-us", "hiring", "vacanc", "opening")


def _is_careers(url: str) -> bool:
    return any(hint in urlsplit(url).path.lower() for hint in _CAREER_PATH_HINTS)


def _score(path: str, anchor: str) -> tuple[int, int]:
    """(strongest hint, number of URL hints). The strongest single hint decides, with a match in the
    URL counting double a match in the link text: summing every hint let marketing-heavy card text
    ("service", "solution", "company"...) outrank a plain /careers link."""
    path, anchor = path.lower(), anchor.lower()[:60]
    best = path_hits = 0
    for hint, weight in PAGE_HINTS:
        if hint in path:
            best = max(best, weight * 2)
            path_hits += 1
        elif hint in anchor:
            best = max(best, weight)
    return best, path_hits


def pick_pages(links: list[tuple[str, str]], base_url: str, limit: int) -> list[str]:
    """The `limit` most promising same-site links, best first, one per path. A careers/jobs page,
    when the site links to one, always gets a slot - hiring is a signal worth a page of the budget."""
    base_host = _host(base_url)
    scored: dict[str, tuple[int, int]] = {}
    for url, anchor in links:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or _host(url) != base_host:
            continue
        if _SKIP_EXTENSIONS.search(parts.path) or parts.path in ("", "/"):
            continue
        score = _score(parts.path, anchor)
        if score[0]:
            clean = f"{parts.scheme}://{parts.netloc}{parts.path}"
            scored[clean] = max(score, scored.get(clean, (0, 0)))
    ranked = [u for u, _ in sorted(scored.items(), key=lambda kv: kv[1], reverse=True)]
    picked = ranked[:limit]
    if limit >= 2 and picked and not any(_is_careers(u) for u in picked):
        careers = next((u for u in ranked[limit:] if _is_careers(u)), None)
        if careers:
            picked[-1] = careers
    return picked


def _to_page(result: FetchResult) -> CrawledPage:
    extracted = extract_page(result.text, result.final_url or result.url)
    return CrawledPage(
        url=result.final_url or result.url,
        title=extracted.title,
        description=extracted.description,
        text=extracted.text,
        fetched_at=datetime.utcnow(),
        links=extracted.links,
    )


async def crawl_site(website: str, fetcher: PageFetcher, max_pages: int) -> CrawlResult:
    """Never raises: an unreadable site comes back as an empty result with a gap."""
    result = CrawlResult()
    home = await fetcher.fetch(website)
    if not home.ok:
        result.home_error = home.error
        result.gaps.append(f"Homepage could not be read ({home.error})")
        return result
    home_page = _to_page(home)
    result.pages.append(home_page)
    result.home_html, result.home_headers = home.text, home.headers

    links = extract_page(home.text, home.final_url or home.url).links
    candidates = [
        u for u in pick_pages(links, home.final_url or home.url, max_pages - 1) if u != home_page.url
    ]

    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def read(url: str) -> FetchResult:
        async with gate:
            return await fetcher.fetch(url)

    for fetched in await asyncio.gather(*(read(u) for u in candidates)):
        if fetched.ok:
            result.pages.append(_to_page(fetched))
        else:
            result.gaps.append(f"{urlsplit(fetched.url).path or '/'} could not be read ({fetched.error})")
    return result
