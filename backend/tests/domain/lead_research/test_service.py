import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.ai.schemas.lead_research import LeadBrief, NewsItem, RegistryFacts
from app.ai.tools.lead_research.dns_posture import DnsPosture
from app.ai.tools.lead_research.public_api import SourceUnavailable
from app.ai.tools.lead_research.site_crawler import CrawledPage, CrawlResult
from app.domain.lead_research import collectors, service
from app.repositories.lead_research_repo import ACTIVE_STATUSES

CONTACT_ID = "507f1f77bcf86cd799439011"


class FakeResearchRepo:
    """In-memory stand-in with the same claim/save semantics as the Mongo repository."""

    def __init__(self):
        self.docs: dict[str, dict] = {}

    async def get(self, contact_id):
        doc = self.docs.get(contact_id)
        return {**doc, "steps": [dict(s) for s in doc.get("steps", [])]} if doc else None

    async def claim(self, contact_id, fields):
        doc = self.docs.get(contact_id)
        if doc and doc.get("status") in ACTIVE_STATUSES:
            return False
        self.docs.setdefault(contact_id, {"contact_id": contact_id, "created_at": datetime.utcnow()}).update(
            fields
        )
        return True

    async def save(self, contact_id, fields):
        self.docs[contact_id].update(fields)

    async def set_step(self, contact_id, name, status):
        for step in self.docs[contact_id]["steps"]:
            if step["name"] == name:
                step["status"] = status

    async def list_statuses(self, limit=1000):
        return list(self.docs.values())

    async def fail_interrupted(self, error):
        n = 0
        for doc in self.docs.values():
            if doc.get("status") in ACTIVE_STATUSES:
                doc.update(status="failed", error=error)
                n += 1
        return n


class FakeContactsRepo:
    def __init__(self, contacts: dict):
        self.contacts = contacts

    async def get_by_id(self, contact_id):
        return self.contacts.get(contact_id)


class FakeFetcher:
    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class FakePublicApi(FakeFetcher):
    """Stands in for PublicApiClient; it records how it was built (user agent, allowed hosts)."""

    built: list[dict] = []

    def __init__(self, **kwargs):
        FakePublicApi.built.append(kwargs)


class FakeCache:
    def __init__(self):
        self.store: dict[tuple[str, str], dict] = {}

    async def get(self, source, key):
        return self.store.get((source, key))

    async def put(self, source, key, payload, ttl_seconds):
        self.store[(source, key)] = payload


def _news(headline="Acme Robotics raises Series B", url="https://news.test/acme-b"):
    return NewsItem(headline=headline, url=url, published_at="2026-03-11", tags=["funding"])


def _page(url="https://acme.com/", text="We build warehouse robots."):
    return CrawledPage(url=url, title="Acme", description="Robots", text=text, fetched_at=datetime.utcnow())


class Harness:
    def __init__(self, monkeypatch, *, contact=None):
        self.repo = FakeResearchRepo()
        self.contact = (
            contact
            if contact is not None
            else {
                "_id": CONTACT_ID,
                "name": "Priya",
                "company": "Acme Robotics",
                "phone": "+919000000000",
                "website": "acme.com",
                "notes": "",
                "lead": {},
            }
        )
        self.crawls = 0
        self.briefs = 0
        self.crawl_result = CrawlResult(pages=[_page()], gaps=["/careers could not be read (timeout)"])
        self.brief = LeadBrief(company_summary="Acme builds robots.", gaps=["Headcount unknown"])
        self.brief_error: Exception | None = None
        self.brief_delay = 0.0
        self.client_projects = None
        self.live_projects = None
        self.news_items = [_news()]
        self.news_error: Exception | None = None
        self.news_delay = 0.0
        self.news_searches = 0
        self.crawl_delay = 0.0
        self.registry_facts: RegistryFacts | None = None
        self.registry_lookups = 0
        self.cache = FakeCache()
        FakePublicApi.built = []

        monkeypatch.setattr(service, "lead_research_repo", self.repo)
        monkeypatch.setattr(service, "contacts_repo", FakeContactsRepo({CONTACT_ID: self.contact}))
        monkeypatch.setattr(service, "PageFetcher", FakeFetcher)
        monkeypatch.setattr(service, "PublicApiClient", FakePublicApi)
        monkeypatch.setattr(service, "source_cache_repo", self.cache)
        monkeypatch.setattr(collectors, "crawl_site", self._crawl)
        monkeypatch.setattr(collectors, "lookup_posture", self._posture)
        monkeypatch.setattr(collectors, "search_google_news", self._news_search)
        monkeypatch.setattr(collectors, "lookup_wikidata", self._wikidata)
        monkeypatch.setattr(service, "generate_brief", self._generate)
        monkeypatch.setattr(service, "get_relevant_projects_for_contact", self._client_projects)
        monkeypatch.setattr(service, "match_projects_from_description", self._live_projects)
        monkeypatch.setattr(
            service,
            "get_settings",
            lambda: SimpleNamespace(
                lead_research_max_concurrent=2,
                lead_research_cache_days=7,
                lead_research_job_timeout_seconds=5.0,
                lead_research_fetch_timeout_seconds=1.0,
                lead_research_max_pages=3,
                lead_research_user_agent="OutboundAI-LeadResearch/1.0",
                lead_research_collector_timeout_seconds=1.0,
                lead_research_news_cache_hours=12,
                lead_research_registry_cache_days=7,
                lead_research_gdelt_enabled=False,
                lead_research_contact="",
            ),
        )
        service._slots = None
        service._background_tasks.clear()

    def configure(self, monkeypatch, **overrides):
        """Re-patch settings with some values changed."""
        base = service.get_settings()
        monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(**{**vars(base), **overrides}))

    async def _news_search(self, api, company):
        self.news_searches += 1
        if self.news_delay:
            await asyncio.sleep(self.news_delay)
        if self.news_error:
            raise self.news_error
        return list(self.news_items)

    async def _wikidata(self, api, company, domain):
        self.registry_lookups += 1
        return self.registry_facts

    async def _crawl(self, website, fetcher, max_pages):
        self.crawls += 1
        if self.crawl_delay:
            await asyncio.sleep(self.crawl_delay)
        return self.crawl_result

    async def _posture(self, domain):
        return DnsPosture(domain=domain, mx=["aspmx.l.google.com"], email_provider="Google Workspace")

    async def _generate(self, evidence):
        self.briefs += 1
        self.evidence = evidence
        if self.brief_delay:
            await asyncio.sleep(self.brief_delay)
        if self.brief_error:
            raise self.brief_error
        return self.brief.model_copy(deep=True)

    async def _client_projects(self, contact_id, phone=""):
        return self.client_projects

    async def _live_projects(self, description):
        self.live_description = description
        return self.live_projects

    async def finish(self):
        await asyncio.gather(*list(service._background_tasks))


@pytest.fixture
def harness(monkeypatch):
    return Harness(monkeypatch)


async def test_unknown_contact_raises(harness):
    with pytest.raises(service.LeadNotFoundError):
        await service.start_research("507f1f77bcf86cd7994390ff")


async def test_contact_without_website_asks_for_one_and_starts_nothing(harness):
    harness.contact["website"] = ""

    doc = await service.start_research(CONTACT_ID)

    assert doc["status"] == "needs_website"
    assert harness.crawls == 0
    assert not service._background_tasks


async def test_unusable_website_is_treated_as_missing(harness):
    harness.contact["website"] = "http://localhost:8080"

    assert (await service.start_research(CONTACT_ID))["status"] == "needs_website"


async def test_happy_path_runs_in_background_and_stores_the_brief(harness):
    started = await service.start_research(CONTACT_ID)
    assert started["status"] == "queued"
    assert started["website"] == "https://acme.com"

    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert doc["status"] == "done"
    assert doc["error"] == ""
    assert doc["brief"]["company_summary"] == "Acme builds robots."
    assert doc["sources"][0]["url"] == "https://acme.com/"
    assert doc["posture"]["email_provider"] == "Google Workspace"
    assert [s["name"] for s in doc["steps"]] == list(service.STEP_ORDER)
    assert {s["name"]: s["status"] for s in doc["steps"]} == {
        **{name: "done" for name in service.STEP_ORDER},
        "check_registry": "skipped",  # no LEAD_RESEARCH_CONTACT configured
    }
    assert doc["is_stale"] is False
    assert [n["headline"] for n in doc["findings"]["news"]] == ["Acme Robotics raises Series B"]
    # crawl gaps, then merge_validate's gaps, then the model's own - without duplicates
    assert doc["brief"]["gaps"] == [
        "/careers could not be read (timeout)",
        "Company facts (Wikidata): not checked (set LEAD_RESEARCH_CONTACT to enable the Wikidata lookup)",
        "Technology detection: nothing found (no recognisable technology signals)",
        "Hiring: nothing found (no careers page among the pages read)",
        "Headcount unknown",
    ]


async def test_second_click_while_running_does_not_start_another_run(harness):
    first = await service.start_research(CONTACT_ID)
    second = await service.start_research(CONTACT_ID)

    await harness.finish()

    assert first["status"] == "queued" and second["status"] in ACTIVE_STATUSES
    assert harness.crawls == 1


async def test_fresh_brief_is_reused_unless_forced(harness):
    await service.start_research(CONTACT_ID)
    await harness.finish()

    reused = await service.start_research(CONTACT_ID)
    assert reused["status"] == "done"
    assert not service._background_tasks or all(t.done() for t in service._background_tasks)
    assert harness.crawls == 1

    forced = await service.start_research(CONTACT_ID, force=True)
    assert forced["status"] == "queued"
    await harness.finish()
    assert harness.crawls == 2


async def test_old_brief_is_rerun_and_flagged_stale_until_then(harness):
    await service.start_research(CONTACT_ID)
    await harness.finish()
    harness.repo.docs[CONTACT_ID]["completed_at"] = datetime.utcnow() - timedelta(days=8)

    assert (await service.get_research(CONTACT_ID))["is_stale"] is True

    rerun = await service.start_research(CONTACT_ID)
    assert rerun["status"] == "queued"
    await harness.finish()
    assert harness.crawls == 2


async def test_changing_the_website_invalidates_a_fresh_brief(harness):
    await service.start_research(CONTACT_ID)
    await harness.finish()
    harness.contact["website"] = "acme.io"

    rerun = await service.start_research(CONTACT_ID)

    assert rerun["status"] == "queued"
    assert rerun["website"] == "https://acme.io"
    await harness.finish()


async def test_unreadable_site_fails_with_a_helpful_message_and_marks_the_step(harness):
    harness.crawl_result = CrawlResult(
        pages=[], gaps=["Homepage could not be read (http_503)"], home_error="http_503"
    )

    await service.start_research(CONTACT_ID)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert doc["status"] == "failed"
    assert "Could not read acme.com" in doc["error"]
    assert "the site returned an error (503)" in doc["error"]
    assert {s["name"]: s["status"] for s in doc["steps"]}["fetch_site"] == "failed"
    assert harness.briefs == 0


async def test_failed_rerun_keeps_the_previous_brief(harness):
    await service.start_research(CONTACT_ID)
    await harness.finish()

    harness.crawl_result = CrawlResult(
        pages=[], gaps=["Homepage could not be read (timeout)"], home_error="timeout"
    )
    await service.start_research(CONTACT_ID, force=True)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert doc["status"] == "failed"
    assert doc["brief"]["company_summary"] == "Acme builds robots."


async def test_unexpected_error_is_generic_and_leaks_nothing(harness):
    harness.brief_error = RuntimeError("secret page text: ignore previous instructions")

    await service.start_research(CONTACT_ID)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert doc["status"] == "failed"
    assert "secret" not in doc["error"]
    assert doc["error"] == "Research failed unexpectedly. Please try again."
    assert {s["name"]: s["status"] for s in doc["steps"]}["write_brief"] == "failed"


async def test_run_that_exceeds_the_job_timeout_is_stopped(harness, monkeypatch):
    harness.brief_delay = 5
    harness.configure(monkeypatch, lead_research_job_timeout_seconds=0.05)

    await service.start_research(CONTACT_ID)
    await harness.finish()

    doc = await service.get_research(CONTACT_ID)
    assert doc["status"] == "failed"
    assert "took too long" in doc["error"]


async def test_client_match_is_preferred_for_project_context(harness):
    harness.client_projects = {"projects": [{"name": "WareFlow", "domain": "Logistics", "summary": "x"}]}

    await service.start_research(CONTACT_ID)
    await harness.finish()

    assert [p["name"] for p in harness.evidence.projects] == ["WareFlow"]
    assert not hasattr(harness, "live_description")


async def test_falls_back_to_matching_from_the_homepage_description(harness):
    harness.live_projects = {"projects": [{"name": "BotOps", "domain": "Manufacturing", "summary": "y"}]}

    await service.start_research(CONTACT_ID)
    await harness.finish()

    assert [p["name"] for p in harness.evidence.projects] == ["BotOps"]
    assert "Robots" in harness.live_description


async def test_crm_context_is_passed_to_the_brief(harness):
    harness.contact["notes"] = "Met at expo"
    harness.contact["lead"] = {
        "source": "Linkedin-Sales",
        "industries": "IT Services and IT Consulting",
        "employees_size": "1,001-5,000 employees",
        "country": "India",
    }

    await service.start_research(CONTACT_ID)
    await harness.finish()

    hints = harness.evidence.crm_hints
    for expected in (
        "Met at expo",
        "Linkedin-Sales",
        "IT Services and IT Consulting",
        "1,001-5,000",
        "India",
    ):
        assert expected in hints


async def test_interrupted_runs_are_failed_on_startup(harness):
    await service.start_research(CONTACT_ID)  # leaves a queued doc; background task not awaited
    for task in list(service._background_tasks):
        task.cancel()
    await asyncio.gather(*service._background_tasks, return_exceptions=True)
    harness.repo.docs[CONTACT_ID]["status"] = "running"

    await service.recover_interrupted_runs()

    doc = await service.get_research(CONTACT_ID)
    assert doc["status"] == "failed"
    assert "server restart" in doc["error"]


async def test_get_research_for_unresearched_contact_is_none(harness):
    assert await service.get_research(CONTACT_ID) is None


# ---- v1: fan-out collectors, merge_validate, cache


def _steps(doc):
    return {s["name"]: s["status"] for s in doc["steps"]}


async def test_a_failing_source_becomes_a_gap_and_a_failed_step_but_the_run_succeeds(harness):
    harness.news_error = SourceUnavailable("rate_limited")

    await service.start_research(CONTACT_ID)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert doc["status"] == "done"
    assert _steps(doc)["find_news"] == "failed" and _steps(doc)["fetch_site"] == "done"
    assert "News: could not be retrieved (unavailable (rate_limited))" in doc["brief"]["gaps"]
    news = next(c for c in doc["findings"]["coverage"] if c["source"] == "news")
    assert news["status"] == "failed" and doc["findings"]["news"] == []


async def test_a_slow_source_is_cut_off_without_failing_the_run(harness, monkeypatch):
    harness.news_delay = 5
    harness.configure(monkeypatch, lead_research_collector_timeout_seconds=0.05)

    await service.start_research(CONTACT_ID)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert doc["status"] == "done" and _steps(doc)["find_news"] == "failed"
    news = next(c for c in doc["findings"]["coverage"] if c["source"] == "news")
    assert news["note"] == "timed out"


async def test_an_unexpected_collector_error_is_contained(harness):
    harness.news_error = ValueError("secret feed content")

    await service.start_research(CONTACT_ID)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert doc["status"] == "done"
    assert "secret" not in str(doc["findings"]) and "secret" not in doc["error"]


async def test_collectors_run_side_by_side_not_one_after_another(harness):
    harness.crawl_delay = 0.4
    harness.news_delay = 0.4

    started = asyncio.get_running_loop().time()
    await service.start_research(CONTACT_ID)
    await harness.finish()
    elapsed = asyncio.get_running_loop().time() - started

    assert (await service.get_research(CONTACT_ID))["status"] == "done"
    assert elapsed < 0.7  # sequential would take at least 0.8


async def test_tech_and_hiring_signals_are_read_from_the_crawl(harness):
    careers = CrawledPage(
        url="https://acme.com/careers",
        title="Careers",
        description="",
        text="Senior Backend Engineer\nOffice Manager",
        fetched_at=datetime.utcnow(),
    )
    harness.crawl_result = CrawlResult(
        pages=[_page(), careers],
        home_html='<link rel="stylesheet" href="/wp-content/a.css">',
        home_headers={"server": "nginx/1.18.0", "cf-ray": "x"},
    )

    await service.start_research(CONTACT_ID)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    names = {t["name"] for t in doc["findings"]["tech"]}
    assert {"WordPress", "nginx", "Cloudflare"} <= names
    assert doc["findings"]["jobs"]["it_roles"] == 1
    assert _steps(doc)["detect_tech"] == "done" and _steps(doc)["find_jobs"] == "done"


async def test_findings_and_citable_sources_reach_the_brief_prompt(harness):
    harness.crawl_result = CrawlResult(pages=[_page()], home_html='<link href="/wp-content/a.css">')

    await service.start_research(CONTACT_ID)
    await harness.finish()

    evidence = harness.evidence
    assert [n.headline for n in evidence.findings.news] == ["Acme Robotics raises Series B"]
    assert {"https://news.test/acme-b", "https://acme.com/", "tech:acme.com"} <= evidence.allowed_sources


async def test_wikidata_is_only_consulted_once_a_contact_is_configured(harness, monkeypatch):
    harness.registry_facts = RegistryFacts(name="Acme", url="https://www.wikidata.org/wiki/Q1", employees=100)

    await service.start_research(CONTACT_ID)
    await harness.finish()
    assert harness.registry_lookups == 0
    assert "@" not in FakePublicApi.built[0]["user_agent"]  # nothing personal is sent unless configured

    harness.configure(monkeypatch, lead_research_contact="ops@example.test")
    await service.start_research(CONTACT_ID, force=True)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert harness.registry_lookups == 1
    assert doc["findings"]["registry"]["employees"] == 100 and _steps(doc)["check_registry"] == "done"
    assert "ops@example.test" in FakePublicApi.built[-1]["user_agent"]  # Wikimedia needs a way to reach us


async def test_the_public_api_client_can_only_reach_the_known_hosts(harness):
    await service.start_research(CONTACT_ID)
    await harness.finish()

    assert FakePublicApi.built[0]["allowed_hosts"] == {
        "news.google.com",
        "api.gdeltproject.org",
        "www.wikidata.org",
    }


async def test_news_is_cached_between_runs(harness):
    await service.start_research(CONTACT_ID)
    await harness.finish()
    await service.start_research(CONTACT_ID, force=True)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert harness.news_searches == 1
    news = next(c for c in doc["findings"]["coverage"] if c["source"] == "news")
    assert news["status"] == "cached" and len(doc["findings"]["news"]) == 1


async def test_a_headcount_conflict_is_flagged_and_passed_to_the_model(harness, monkeypatch):
    harness.contact["lead"] = {"employees_size": "5,001-10,000 employees"}
    harness.registry_facts = RegistryFacts(
        name="Acme", url="https://www.wikidata.org/wiki/Q1", employees=1100
    )
    harness.configure(monkeypatch, lead_research_contact="ops@example.test")

    await service.start_research(CONTACT_ID)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    (conflict,) = doc["findings"]["conflicts"]
    assert "5,001-10,000" in conflict and "1,100" in conflict
    assert harness.evidence.findings.conflicts == [conflict]


async def test_an_unreadable_site_still_fails_the_run_even_if_other_sources_worked(harness):
    harness.crawl_result = CrawlResult(pages=[], home_error="blocked_by_robots")

    await service.start_research(CONTACT_ID)
    await harness.finish()
    doc = await service.get_research(CONTACT_ID)

    assert doc["status"] == "failed" and "asks automated tools not to read it" in doc["error"]
    assert harness.briefs == 0 and _steps(doc)["fetch_site"] == "failed"
