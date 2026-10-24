"""Collector nodes for lead research.

Each collector returns a `Collected` - its data plus a `SourceStatus` saying whether it found
something, found nothing, came from cache, was skipped, or failed. `guarded` makes sure a slow
or broken source can only ever produce a "failed" status: a flaky free source must never stop
a research run (plan: "a failed collector never stops the run").
"""

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any

from app.ai.schemas.lead_research import NewsItem, RegistryFacts, SourceStatus
from app.ai.tools.lead_research.dns_posture import lookup_posture
from app.ai.tools.lead_research.job_signals import find_jobs
from app.ai.tools.lead_research.news_feeds import (
    clean_company_name,
    merge_news,
    search_gdelt,
    search_google_news,
)
from app.ai.tools.lead_research.page_fetcher import PageFetcher
from app.ai.tools.lead_research.public_api import PublicApiClient, SourceUnavailable
from app.ai.tools.lead_research.site_crawler import CrawlResult, crawl_site
from app.ai.tools.lead_research.tech_fingerprint import detect_technologies
from app.ai.tools.lead_research.wikidata import lookup_wikidata

logger = logging.getLogger(__name__)

HOUR = 3600
DAY = 24 * HOUR
EMPTY_NEWS_TTL = 3 * HOUR  # remember "no news" briefly so a quiet company doesn't re-hit the feed every run
EMPTY_REGISTRY_TTL = DAY

_FETCH_ERROR_REASONS = {
    "host_not_found": "that website address doesn't exist",
    "unsafe_address": "that address isn't a public website",
    "blocked_by_robots": "the site asks automated tools not to read it",
    "timeout": "the site took too long to respond",
    "network_error": "the connection failed",
    "not_html": "it isn't a normal web page",
    "too_many_redirects": "it redirects in a loop",
}


def fetch_error_reason(code: str) -> str:
    if code.startswith("http_"):
        return f"the site returned an error ({code[5:]})"
    return _FETCH_ERROR_REASONS.get(code, "no pages were readable")


@dataclass
class Collected:
    data: Any
    status: SourceStatus


def _result(source: str, data: Any, status: str, note: str = "") -> Collected:
    return Collected(data, SourceStatus(source=source, status=status, note=note))


async def guarded(source: str, work: Awaitable[Collected], timeout: float) -> Collected:
    """Run one collector and turn any failure into a 'failed' result. Never raises (except cancellation)."""
    try:
        return await asyncio.wait_for(work, timeout)
    except asyncio.TimeoutError:
        return _result(source, None, "failed", "timed out")
    except SourceUnavailable as e:
        return _result(source, None, "failed", f"unavailable ({e})")
    except Exception as e:
        # Type only: exception text can carry page or feed content.
        logger.error(f"[LEAD-RESEARCH] Collector failed source={source} error={type(e).__name__}")
        return _result(source, None, "failed", "unexpected error")


async def collect_site(website: str, fetcher: PageFetcher, max_pages: int) -> Collected:
    crawl = await crawl_site(website, fetcher, max_pages)
    if not crawl.pages:
        return _result("site", crawl, "failed", fetch_error_reason(crawl.home_error))
    return _result("site", crawl, "ok", f"{len(crawl.pages)} pages read")


async def collect_email_dns(domain: str) -> Collected:
    posture = await lookup_posture(domain)
    if not (posture.mx or posture.spf or posture.dmarc):
        return _result("email_dns", posture, "empty", "no mail records found")
    return _result("email_dns", posture, "ok")


async def collect_news(
    api: PublicApiClient, cache, company: str, *, gdelt_enabled: bool, ttl_seconds: int
) -> Collected:
    name = clean_company_name(company)
    if not name:
        return _result("news", [], "skipped", "company name too short to search")
    key = name.lower()

    cached = await cache.get("news", key)
    if cached is not None:
        items = [NewsItem.model_validate(i) for i in cached["items"]]
        return _result(
            "news", items, "cached" if items else "empty", "" if items else f"no recent news names {name}"
        )

    searches = [search_google_news(api, company)]
    if gdelt_enabled:
        searches.append(search_gdelt(api, company))
    outcomes = await asyncio.gather(*searches, return_exceptions=True)
    groups = [o for o in outcomes if isinstance(o, list)]
    if not groups:
        raise next(o for o in outcomes if isinstance(o, BaseException))  # `guarded` reports it
    items = merge_news(*groups)
    await cache.put(
        "news", key, {"items": [i.model_dump() for i in items]}, ttl_seconds if items else EMPTY_NEWS_TTL
    )
    return _result("news", items, "ok" if items else "empty", "" if items else f"no recent news names {name}")


async def collect_registry(
    api: PublicApiClient | None, cache, company: str, domain: str, *, ttl_seconds: int
) -> Collected:
    if api is None:
        return _result("registry", None, "skipped", "set LEAD_RESEARCH_CONTACT to enable the Wikidata lookup")
    key = domain.lower()

    cached = await cache.get("wikidata", key)
    if cached is not None:
        facts = RegistryFacts.model_validate(cached["facts"]) if cached["facts"] else None
        return _result(
            "registry",
            facts,
            "cached" if facts else "empty",
            "" if facts else "no Wikidata entry for this website",
        )

    facts = await lookup_wikidata(api, company, domain)
    await cache.put(
        "wikidata",
        key,
        {"facts": facts.model_dump() if facts else None},
        ttl_seconds if facts else EMPTY_REGISTRY_TTL,
    )
    return _result(
        "registry", facts, "ok" if facts else "empty", "" if facts else "no Wikidata entry for this website"
    )


async def collect_tech(crawl: CrawlResult) -> Collected:
    findings = detect_technologies(crawl.home_html, crawl.home_headers)
    return _result(
        "tech",
        findings,
        "ok" if findings else "empty",
        "" if findings else "no recognisable technology signals",
    )


async def collect_jobs(crawl: CrawlResult) -> Collected:
    jobs = find_jobs(crawl.pages)
    if jobs is None:
        return _result("jobs", None, "empty", "no careers page among the pages read")
    if not jobs.postings:
        return _result(
            "jobs",
            jobs,
            "empty",
            "careers page found but no listings readable (loaded by JavaScript or an external board)",
        )
    return _result("jobs", jobs, "ok", f"{jobs.it_roles} IT-related of {len(jobs.postings)} roles")
