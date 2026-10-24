import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.ai.schemas.lead_research import LeadBrief
from app.ai.tools.lead_research.dns_posture import DnsPosture
from app.ai.tools.lead_research.site_crawler import CrawledPage, CrawlResult
from app.domain.lead_research import service
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

        monkeypatch.setattr(service, "lead_research_repo", self.repo)
        monkeypatch.setattr(service, "contacts_repo", FakeContactsRepo({CONTACT_ID: self.contact}))
        monkeypatch.setattr(service, "PageFetcher", FakeFetcher)
        monkeypatch.setattr(service, "crawl_site", self._crawl)
        monkeypatch.setattr(service, "lookup_posture", self._posture)
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
            ),
        )
        service._slots = None
        service._background_tasks.clear()

    async def _crawl(self, website, fetcher, max_pages):
        self.crawls += 1
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
    assert [s["status"] for s in doc["steps"]] == ["done"] * 4
    assert doc["is_stale"] is False
    # collector gaps and the model's own gaps are merged, without duplicates
    assert doc["brief"]["gaps"] == ["/careers could not be read (timeout)", "Headcount unknown"]


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
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            lead_research_max_concurrent=2,
            lead_research_cache_days=7,
            lead_research_job_timeout_seconds=0.05,
            lead_research_fetch_timeout_seconds=1.0,
            lead_research_max_pages=3,
            lead_research_user_agent="OutboundAI-LeadResearch/1.0",
        ),
    )

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
    assert phrase in service._fetch_error_reason(code)
