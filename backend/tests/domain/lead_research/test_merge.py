from datetime import datetime

import pytest

from app.ai.schemas.lead_research import (
    JobPosting,
    JobsFinding,
    NewsItem,
    RegistryFacts,
    SourceStatus,
    TechFinding,
)
from app.ai.tools.lead_research.site_crawler import CrawledPage
from app.domain.lead_research.merge import merge_findings, parse_employee_range


def _page(url="https://acme.com/"):
    return CrawledPage(url=url, title="", description="", text="", fetched_at=datetime.utcnow())


def _status(source, status="ok", note=""):
    return SourceStatus(source=source, status=status, note=note)


def _merge(**overrides):
    base = dict(
        domain="acme.com",
        pages=[_page(), _page("https://acme.com/about")],
        tech=[],
        jobs=None,
        news=[],
        registry=None,
        statuses=[_status("site")],
    )
    return merge_findings(**{**base, **overrides})


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1,001-5,000 employees", (1001, 5000)),
        ("51-200 employees", (51, 200)),
        ("1–10 employees", (1, 10)),
        ("10,001+ employees", (10001, None)),
        ("11 to 50", (11, 50)),
        ("lots", None),
        ("", None),
    ],
)
def test_parse_employee_range(text, expected):
    assert parse_employee_range(text) == expected


def _registry(employees):
    return RegistryFacts(name="Acme", url="https://www.wikidata.org/wiki/Q1", employees=employees)


def test_wildly_different_headcounts_are_flagged_as_a_conflict():
    merged = _merge(registry=_registry(1100), crm_employees="5,001-10,000 employees")

    (conflict,) = merged.findings.conflicts
    assert "5,001-10,000 employees" in conflict and "1,100" in conflict and "out of date" in conflict


def test_registry_far_above_the_range_is_also_a_conflict():
    assert _merge(registry=_registry(50000), crm_employees="1-10 employees").findings.conflicts


@pytest.mark.parametrize(
    "employees, crm",
    [
        (1100, "1,001-5,000 employees"),  # inside the range
        (900, "1,001-5,000 employees"),  # a little under: Wikidata is often stale
        (8000, "1,001-5,000 employees"),  # a little over
        (50000, "10,001+ employees"),
        (100, ""),  # nothing to compare against
        (100, "lots of people"),  # unparseable
    ],
)
def test_close_or_uncomparable_headcounts_are_not_conflicts(employees, crm):
    assert _merge(registry=_registry(employees), crm_employees=crm).findings.conflicts == []


def test_no_registry_or_no_headcount_means_no_conflict():
    assert _merge(registry=None, crm_employees="1-10").findings.conflicts == []
    assert _merge(registry=_registry(None), crm_employees="1-10").findings.conflicts == []


def test_failed_skipped_and_empty_sources_become_plain_language_gaps():
    merged = _merge(
        statuses=[
            _status("site"),
            _status("news", "failed", "unavailable (rate_limited)"),
            _status("registry", "skipped", "set LEAD_RESEARCH_CONTACT to enable the Wikidata lookup"),
            _status("jobs", "empty", "no careers page among the pages read"),
            _status("tech", "empty", "no recognisable technology signals"),
            _status("email_dns", "empty", "no mail records found"),
        ]
    )

    assert merged.gaps == [
        "News: could not be retrieved (unavailable (rate_limited))",
        "Company facts (Wikidata): not checked (set LEAD_RESEARCH_CONTACT to enable the Wikidata lookup)",
        "Hiring: nothing found (no careers page among the pages read)",
        "Technology detection: nothing found (no recognisable technology signals)",
    ]  # an empty email/DNS result isn't worth a gap; the brief already says there is no email setup


def test_healthy_and_cached_sources_produce_no_gaps_and_coverage_is_kept():
    statuses = [_status("site"), _status("news", "cached"), _status("registry")]

    merged = _merge(statuses=statuses)

    assert merged.gaps == [] and merged.findings.coverage == statuses


def test_every_source_a_claim_may_cite_is_listed():
    news = [NewsItem(headline="Acme raises", url="https://news.test/a")]
    jobs = JobsFinding(
        careers_url="https://acme.com/careers",
        postings=[JobPosting(title="SRE", url="https://acme.com/careers/sre", it_related=True)],
    )
    tech = [TechFinding(name="WordPress", category="cms", evidence="x")]

    merged = _merge(news=news, jobs=jobs, tech=tech, registry=_registry(10))

    assert merged.allowed_sources == {
        "https://acme.com/",
        "https://acme.com/about",
        "https://news.test/a",
        "https://www.wikidata.org/wiki/Q1",
        "tech:acme.com",
        "https://acme.com/careers",
        "https://acme.com/careers/sre",
    }


def test_no_tech_means_no_tech_pseudo_source():
    assert "tech:acme.com" not in _merge().allowed_sources


def test_duplicate_and_unsafe_news_links_are_dropped():
    news = [
        NewsItem(headline="A", url="https://news.test/a"),
        NewsItem(headline="A again", url="https://news.test/a"),
        NewsItem(headline="Bad", url="javascript:alert(1)"),
    ]

    merged = _merge(news=news)

    assert [n.headline for n in merged.findings.news] == ["A"]
    assert "javascript:alert(1)" not in merged.allowed_sources


def test_technology_is_grouped_by_category_order():
    tech = [
        TechFinding(name="Cloudflare", category="hosting", evidence="h"),
        TechFinding(name="Stripe", category="payments", evidence="p"),
        TechFinding(name="WordPress", category="cms", evidence="c"),
        TechFinding(name="Mystery", category="other", evidence="m"),
    ]

    assert [t.name for t in _merge(tech=tech).findings.tech] == [
        "WordPress",
        "Stripe",
        "Cloudflare",
        "Mystery",
    ]
