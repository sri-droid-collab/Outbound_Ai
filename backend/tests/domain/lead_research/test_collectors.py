import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.ai.schemas.lead_research import NewsItem, RegistryFacts
from app.ai.tools.lead_research.dns_posture import DnsPosture
from app.ai.tools.lead_research.public_api import SourceUnavailable
from app.ai.tools.lead_research.site_crawler import CrawledPage, CrawlResult
from app.domain.lead_research import collectors
from app.domain.lead_research.collectors import (
    Collected,
    collect_email_dns,
    collect_jobs,
    collect_news,
    collect_registry,
    collect_site,
    collect_tech,
    fetch_error_reason,
    guarded,
)


class FakeCache:
    def __init__(self):
        self.store: dict[tuple[str, str], dict] = {}
        self.puts: list[tuple[str, str, int]] = []

    async def get(self, source, key):
        return self.store.get((source, key))

    async def put(self, source, key, payload, ttl_seconds):
        self.store[(source, key)] = payload
        self.puts.append((source, key, ttl_seconds))


def _news(headline="Acme raises Series B"):
    return NewsItem(
        headline=headline, url=f"https://x.test/{headline[:4]}", published_at="2026-03-11", tags=["funding"]
    )


def _facts():
    return RegistryFacts(name="Acme", url="https://www.wikidata.org/wiki/Q1", employees=100)


# ---- guarded


async def _ok():
    return Collected("data", collectors.SourceStatus(source="x", status="ok"))


async def test_guarded_passes_a_successful_result_through():
    assert (await guarded("x", _ok(), 1.0)).data == "data"


async def test_guarded_turns_a_timeout_into_a_failed_status():
    async def slow():
        await asyncio.sleep(5)

    result = await guarded("news", slow(), 0.01)

    assert result.data is None
    assert (result.status.source, result.status.status, result.status.note) == ("news", "failed", "timed out")


async def test_guarded_reports_an_unavailable_source_with_its_reason():
    async def limited():
        raise SourceUnavailable("rate_limited")

    result = await guarded("news", limited(), 1.0)

    assert result.status.status == "failed" and "rate_limited" in result.status.note


async def test_guarded_swallows_unexpected_errors_and_logs_only_the_type(caplog):
    async def boom():
        raise ValueError("secret page content")

    with caplog.at_level("ERROR"):
        result = await guarded("tech", boom(), 1.0)

    assert result.status.status == "failed" and result.status.note == "unexpected error"
    assert "secret" not in caplog.text and "ValueError" in caplog.text


# ---- news


async def test_news_miss_searches_caches_and_reports_ok(monkeypatch):
    cache = FakeCache()
    search = AsyncMock(return_value=[_news()])
    monkeypatch.setattr(collectors, "search_google_news", search)

    result = await collect_news(
        object(), cache, "Acme Robotics Pvt Ltd", gdelt_enabled=False, ttl_seconds=3600
    )

    assert result.status.status == "ok" and [n.headline for n in result.data] == ["Acme raises Series B"]
    assert cache.puts == [("news", "acme robotics", 3600)]


async def test_news_hit_is_served_from_cache_without_a_request(monkeypatch):
    cache = FakeCache()
    cache.store[("news", "acme")] = {"items": [_news().model_dump()]}
    search = AsyncMock(side_effect=AssertionError("must not search"))
    monkeypatch.setattr(collectors, "search_google_news", search)

    result = await collect_news(object(), cache, "Acme", gdelt_enabled=False, ttl_seconds=3600)

    assert result.status.status == "cached" and result.data[0].tags == ["funding"]


async def test_no_news_is_cached_briefly_and_reported_as_empty(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(collectors, "search_google_news", AsyncMock(return_value=[]))

    result = await collect_news(object(), cache, "Acme", gdelt_enabled=False, ttl_seconds=12 * 3600)

    assert result.status.status == "empty" and result.data == []
    assert cache.puts[0][2] == collectors.EMPTY_NEWS_TTL < 12 * 3600


async def test_cached_empty_result_does_not_search_again(monkeypatch):
    cache = FakeCache()
    cache.store[("news", "acme")] = {"items": []}
    monkeypatch.setattr(collectors, "search_google_news", AsyncMock(side_effect=AssertionError))

    result = await collect_news(object(), cache, "Acme", gdelt_enabled=False, ttl_seconds=60)

    assert result.status.status == "empty"


async def test_failures_are_never_cached(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(collectors, "search_google_news", AsyncMock(side_effect=SourceUnavailable("timeout")))

    with pytest.raises(SourceUnavailable):
        await collect_news(object(), cache, "Acme", gdelt_enabled=False, ttl_seconds=60)

    assert cache.puts == []


async def test_gdelt_failing_does_not_hurt_when_google_news_worked(monkeypatch):
    monkeypatch.setattr(
        collectors, "search_google_news", AsyncMock(return_value=[_news("Acme raises Series B")])
    )
    monkeypatch.setattr(collectors, "search_gdelt", AsyncMock(side_effect=SourceUnavailable("rate_limited")))

    result = await collect_news(object(), FakeCache(), "Acme", gdelt_enabled=True, ttl_seconds=60)

    assert result.status.status == "ok" and len(result.data) == 1


async def test_both_sources_are_merged_when_gdelt_is_enabled(monkeypatch):
    monkeypatch.setattr(
        collectors, "search_google_news", AsyncMock(return_value=[_news("Acme raises Series B")])
    )
    monkeypatch.setattr(
        collectors, "search_gdelt", AsyncMock(return_value=[_news("Acme opens a new office")])
    )

    result = await collect_news(object(), FakeCache(), "Acme", gdelt_enabled=True, ttl_seconds=60)

    assert {n.headline for n in result.data} == {"Acme raises Series B", "Acme opens a new office"}


async def test_gdelt_is_not_called_unless_enabled(monkeypatch):
    monkeypatch.setattr(collectors, "search_google_news", AsyncMock(return_value=[]))
    monkeypatch.setattr(collectors, "search_gdelt", AsyncMock(side_effect=AssertionError("must stay off")))

    await collect_news(object(), FakeCache(), "Acme", gdelt_enabled=False, ttl_seconds=60)


async def test_a_company_name_too_short_to_search_is_skipped(monkeypatch):
    monkeypatch.setattr(collectors, "search_google_news", AsyncMock(side_effect=AssertionError))

    result = await collect_news(object(), FakeCache(), "Co", gdelt_enabled=False, ttl_seconds=60)

    assert result.status.status == "skipped" and result.data == []


# ---- registry


async def test_registry_is_skipped_until_a_contact_is_configured():
    result = await collect_registry(None, FakeCache(), "Acme", "acme.com", ttl_seconds=60)

    assert result.status.status == "skipped" and "LEAD_RESEARCH_CONTACT" in result.status.note


async def test_registry_hit_after_miss_uses_the_cache(monkeypatch):
    cache = FakeCache()
    lookup = AsyncMock(return_value=_facts())
    monkeypatch.setattr(collectors, "lookup_wikidata", lookup)

    first = await collect_registry(object(), cache, "Acme", "acme.com", ttl_seconds=7 * 86400)
    second = await collect_registry(object(), cache, "Acme", "ACME.com", ttl_seconds=7 * 86400)

    assert first.status.status == "ok" and second.status.status == "cached"
    assert second.data.employees == 100 and lookup.await_count == 1
    assert cache.puts == [("wikidata", "acme.com", 7 * 86400)]


async def test_no_registry_entry_is_remembered_so_it_is_not_looked_up_every_run(monkeypatch):
    cache = FakeCache()
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(collectors, "lookup_wikidata", lookup)

    first = await collect_registry(object(), cache, "Local Bakery", "bakery.example", ttl_seconds=7 * 86400)
    second = await collect_registry(object(), cache, "Local Bakery", "bakery.example", ttl_seconds=7 * 86400)

    assert first.status.status == second.status.status == "empty"
    assert lookup.await_count == 1 and cache.puts[0][2] == collectors.EMPTY_REGISTRY_TTL


async def test_registry_failure_is_not_cached(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(collectors, "lookup_wikidata", AsyncMock(side_effect=SourceUnavailable("http_403")))

    with pytest.raises(SourceUnavailable):
        await collect_registry(object(), cache, "Acme", "acme.com", ttl_seconds=60)

    assert cache.puts == []


# ---- crawl-derived collectors


def _page(url="https://acme.com/", text="Hello", links=()):
    return CrawledPage(
        url=url, title="", description="", text=text, fetched_at=datetime.utcnow(), links=list(links)
    )


async def test_site_collector_reports_pages_read(monkeypatch):
    crawl = CrawlResult(pages=[_page(), _page("https://acme.com/about")])
    monkeypatch.setattr(collectors, "crawl_site", AsyncMock(return_value=crawl))

    result = await collect_site("https://acme.com", object(), 5)

    assert result.status.status == "ok" and result.status.note == "2 pages read" and result.data is crawl


async def test_unreadable_site_is_failed_with_a_plain_reason(monkeypatch):
    crawl = CrawlResult(
        home_error="blocked_by_robots", gaps=["Homepage could not be read (blocked_by_robots)"]
    )
    monkeypatch.setattr(collectors, "crawl_site", AsyncMock(return_value=crawl))

    result = await collect_site("https://acme.com", object(), 5)

    assert result.status.status == "failed" and "asks automated tools not to read it" in result.status.note


@pytest.mark.parametrize(
    "code, phrase",
    [
        ("host_not_found", "that website address doesn't exist"),
        ("blocked_by_robots", "asks automated tools not to read it"),
        ("timeout", "took too long to respond"),
        ("http_404", "the site returned an error (404)"),
        ("something_new", "no pages were readable"),
    ],
)
def test_fetch_error_codes_become_plain_language(code, phrase):
    assert phrase in fetch_error_reason(code)


async def test_tech_collector_statuses():
    wordpress = CrawlResult(home_html='<link href="/wp-content/x.css">', home_headers={})
    plain = CrawlResult(home_html="<p>hi</p>", home_headers={})

    found = await collect_tech(wordpress)
    nothing = await collect_tech(plain)

    assert found.status.status == "ok" and found.data[0].name == "WordPress"
    assert nothing.status.status == "empty" and nothing.data == []


async def test_jobs_collector_distinguishes_roles_found_empty_page_and_no_page():
    with_roles = CrawlResult(
        pages=[_page("https://acme.com/careers", "Senior Backend Engineer\nData Scientist")]
    )
    no_listings = CrawlResult(pages=[_page("https://acme.com/careers", "We are hiring!")])
    no_page = CrawlResult(pages=[_page()])

    a, b, c = await collect_jobs(with_roles), await collect_jobs(no_listings), await collect_jobs(no_page)

    assert a.status.status == "ok" and "2 IT-related of 2" in a.status.note
    assert b.status.status == "empty" and "JavaScript" in b.status.note and b.data is not None
    assert c.status.status == "empty" and c.data is None


async def test_email_dns_collector(monkeypatch):
    with_records = DnsPosture(domain="acme.com", mx=["mx.acme.com"])
    monkeypatch.setattr(collectors, "lookup_posture", AsyncMock(return_value=with_records))
    assert (await collect_email_dns("acme.com")).status.status == "ok"

    monkeypatch.setattr(collectors, "lookup_posture", AsyncMock(return_value=DnsPosture(domain="acme.com")))
    assert (await collect_email_dns("acme.com")).status.status == "empty"
