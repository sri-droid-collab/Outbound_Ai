"""Lead research orchestration.

`start_research` claims a run atomically and returns immediately; the work
itself runs as a background task, reporting progress by updating the stored
document, which is all the frontend polls. A research run is therefore
independent of the browser tab that started it.

Pipeline (fan-out, fan-in):
  1. In parallel, each time-boxed: read the site, check email DNS, find news, look up Wikidata.
  2. From the crawl: detect technology, find IT hiring signals.
  3. merge_validate: combine, attach sources, record gaps, flag conflicts.
  4. Match our past projects, write the brief from all of it.
A failed or slow source becomes a gap in the brief, never a failed run - except an unreadable
website, since without it there is nothing to write about.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from app.ai.agents.client_domain_agent import (
    get_relevant_projects_for_contact,
    match_projects_from_description,
)
from app.ai.agents.lead_research_agent import ResearchEvidence, generate_brief
from app.ai.tools.lead_research.news_feeds import NEWS_HOSTS
from app.ai.tools.lead_research.page_fetcher import PageFetcher
from app.ai.tools.lead_research.public_api import PublicApiClient
from app.ai.tools.lead_research.site_crawler import CrawlResult
from app.ai.tools.lead_research.url_safety import normalize_website, site_domain
from app.ai.tools.lead_research.wikidata import WIKIDATA_HOSTS
from app.config import get_settings
from app.domain.lead_research.collectors import (
    Collected,
    collect_email_dns,
    collect_jobs,
    collect_news,
    collect_registry,
    collect_site,
    collect_tech,
    guarded,
)
from app.domain.lead_research.merge import merge_findings
from app.repositories.contacts_repo import contacts_repo
from app.repositories.lead_research_repo import ACTIVE_STATUSES, lead_research_repo
from app.repositories.source_cache_repo import source_cache_repo

logger = logging.getLogger(__name__)

STEP_ORDER = (
    "fetch_site",
    "check_email_setup",
    "find_news",
    "check_registry",
    "detect_tech",
    "find_jobs",
    "merge_findings",
    "match_projects",
    "write_brief",
)

_background_tasks: set[asyncio.Task] = set()
_slots: asyncio.Semaphore | None = None


class LeadNotFoundError(Exception):
    pass


class ResearchError(Exception):
    """An expected failure whose message is safe to show the user."""


def _research_slots() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(max(1, get_settings().lead_research_max_concurrent))
    return _slots


def _initial_steps() -> list[dict]:
    return [{"name": name, "status": "pending"} for name in STEP_ORDER]


def _is_fresh(doc: dict, website: str) -> bool:
    completed = doc.get("completed_at")
    max_age = timedelta(days=get_settings().lead_research_cache_days)
    return (
        doc.get("status") == "done"
        and doc.get("website") == website
        and completed is not None
        and datetime.utcnow() - completed < max_age
    )


def _with_staleness(doc: dict) -> dict:
    completed = doc.get("completed_at")
    max_age = timedelta(days=get_settings().lead_research_cache_days)
    is_stale = bool(doc.get("brief")) and completed is not None and datetime.utcnow() - completed >= max_age
    return {**doc, "is_stale": is_stale}


async def get_research(contact_id: str) -> dict | None:
    doc = await lead_research_repo.get(contact_id)
    return _with_staleness(doc) if doc else None


async def list_research_statuses() -> list[dict]:
    return await lead_research_repo.list_statuses()


async def recover_interrupted_runs() -> None:
    """Runs live in this process, so any left queued/running at startup died with it."""
    count = await lead_research_repo.fail_interrupted("Interrupted by a server restart. Run it again.")
    if count:
        logger.warning(f"[LEAD-RESEARCH] Marked {count} interrupted run(s) as failed")


async def start_research(contact_id: str, force: bool = False) -> dict:
    """Start (or return the in-flight / fresh) research for a contact."""
    contact = await contacts_repo.get_by_id(contact_id)
    if not contact:
        raise LeadNotFoundError(contact_id)

    existing = await lead_research_repo.get(contact_id)
    if existing and existing.get("status") in ACTIVE_STATUSES:
        return _with_staleness(existing)

    website = normalize_website(contact.get("website", ""))
    if not website:
        await lead_research_repo.claim(
            contact_id,
            {"status": "needs_website", "website": "", "steps": _initial_steps(), "error": ""},
        )
        return _with_staleness(await lead_research_repo.get(contact_id))

    if existing and not force and _is_fresh(existing, website):
        return _with_staleness(existing)

    claimed = await lead_research_repo.claim(
        contact_id,
        {
            "status": "queued",
            "website": website,
            "steps": _initial_steps(),
            "error": "",
            "started_at": datetime.utcnow(),
            "completed_at": None,
            "updated_at": datetime.utcnow(),
        },
    )
    if claimed:
        task = asyncio.create_task(_run(contact_id))
        _background_tasks.add(task)  # the loop only keeps weak references to tasks
        task.add_done_callback(_background_tasks.discard)
    return _with_staleness(await lead_research_repo.get(contact_id))


async def _run(contact_id: str) -> None:
    """Background task. Records every outcome on the document; never raises."""
    try:
        async with _research_slots():
            await lead_research_repo.save(contact_id, {"status": "running"})
            await asyncio.wait_for(_execute(contact_id), get_settings().lead_research_job_timeout_seconds)
    except ResearchError as e:
        await _fail(contact_id, str(e))
    except asyncio.TimeoutError:
        await _fail(contact_id, "Research took too long and was stopped. Please try again.")
    except Exception as e:
        # Type only: exception text can carry page or model content.
        logger.error(f"[LEAD-RESEARCH] Run failed contact={contact_id} error={type(e).__name__}")
        logger.debug("[LEAD-RESEARCH] traceback", exc_info=True)
        await _fail(contact_id, "Research failed unexpectedly. Please try again.")


async def _fail(contact_id: str, message: str) -> None:
    try:
        await lead_research_repo.save(contact_id, {"status": "failed", "error": message})
    except Exception as e:
        logger.error(
            f"[LEAD-RESEARCH] Could not record failure contact={contact_id} error={type(e).__name__}"
        )


async def _step(contact_id: str, name: str, status: str) -> None:
    await lead_research_repo.set_step(contact_id, name, status)


async def _tracked(contact_id: str, name: str, work):
    await _step(contact_id, name, "running")
    try:
        result = await work
    except Exception:
        await _step(contact_id, name, "failed")
        raise
    await _step(contact_id, name, "done")
    return result


_STEP_STATE = {"failed": "failed", "skipped": "skipped"}


async def _collect(contact_id: str, step: str, source: str, work, timeout: float) -> Collected:
    """Run one collector as a tracked step. A failed or skipped source is reflected in its
    step state but never raises - the run carries on without it."""
    await _step(contact_id, step, "running")
    collected = await guarded(source, work, timeout)
    await _step(contact_id, step, _STEP_STATE.get(collected.status.status, "done"))
    return collected


def _api_user_agent(settings) -> str:
    """Wikimedia blocks clients it can't contact, so the contact (when configured) goes in the User-Agent."""
    if settings.lead_research_contact:
        return f"OutboundAI-LeadResearch/1.0 ({settings.lead_research_contact}; business research)"
    return settings.lead_research_user_agent


async def _execute(contact_id: str) -> None:
    settings = get_settings()
    contact = await contacts_repo.get_by_id(contact_id)
    doc = await lead_research_repo.get(contact_id)
    if not contact or not doc:
        raise ResearchError("This lead no longer exists.")

    website = doc["website"]
    domain = site_domain(website)
    company = contact.get("company", "")
    lead = contact.get("lead") or {}
    timeout = settings.lead_research_collector_timeout_seconds

    async with (
        PageFetcher(
            user_agent=settings.lead_research_user_agent, timeout=settings.lead_research_fetch_timeout_seconds
        ) as fetcher,
        PublicApiClient(
            user_agent=_api_user_agent(settings),
            timeout=settings.lead_research_fetch_timeout_seconds,
            allowed_hosts=NEWS_HOSTS | WIKIDATA_HOSTS,
        ) as api,
    ):
        # Fan-out: independent sources run side by side.
        site, dns, news, registry = await asyncio.gather(
            _collect(
                contact_id,
                "fetch_site",
                "site",
                collect_site(website, fetcher, settings.lead_research_max_pages),
                settings.lead_research_job_timeout_seconds,
            ),
            _collect(contact_id, "check_email_setup", "email_dns", collect_email_dns(domain), timeout),
            _collect(
                contact_id,
                "find_news",
                "news",
                collect_news(
                    api,
                    source_cache_repo,
                    company,
                    gdelt_enabled=settings.lead_research_gdelt_enabled,
                    ttl_seconds=settings.lead_research_news_cache_hours * 3600,
                ),
                timeout,
            ),
            _collect(
                contact_id,
                "check_registry",
                "registry",
                collect_registry(
                    api if settings.lead_research_contact else None,
                    source_cache_repo,
                    company,
                    domain,
                    ttl_seconds=settings.lead_research_registry_cache_days * 86400,
                ),
                timeout,
            ),
        )

    crawl: CrawlResult | None = site.data
    if crawl is None or not crawl.pages:
        raise ResearchError(
            f"Could not read {domain}: {site.status.note or 'no pages were readable'}. "
            "Check the website address and try again."
        )

    # These read the crawl, so they run once it is in.
    tech, jobs = await asyncio.gather(
        _collect(contact_id, "detect_tech", "tech", collect_tech(crawl), timeout),
        _collect(contact_id, "find_jobs", "jobs", collect_jobs(crawl), timeout),
    )

    # Fan-in.
    await _step(contact_id, "merge_findings", "running")
    merged = merge_findings(
        domain=domain,
        pages=crawl.pages,
        tech=tech.data or [],
        jobs=jobs.data,
        news=news.data or [],
        registry=registry.data,
        statuses=[c.status for c in (site, dns, news, registry, tech, jobs)],
        crm_employees=lead.get("employees_size", ""),
    )
    await _step(contact_id, "merge_findings", "done")

    projects = await _tracked(contact_id, "match_projects", _matching_projects(contact, crawl))

    posture = dns.data
    evidence = ResearchEvidence(
        contact_name=contact["name"],
        company=company,
        website=website,
        domain=domain,
        crm_hints=_crm_hints(contact),
        pages=[
            {"url": p.url, "title": p.title, "description": p.description, "text": p.text}
            for p in crawl.pages
        ],
        email_setup=posture.describe() if posture and (posture.mx or posture.spf or posture.dmarc) else None,
        projects=projects,
        findings=merged.findings,
        allowed_sources=merged.allowed_sources,
    )
    brief = await _tracked(contact_id, "write_brief", generate_brief(evidence))
    brief.gaps = list(dict.fromkeys([*crawl.gaps, *merged.gaps, *brief.gaps]))

    await lead_research_repo.save(
        contact_id,
        {
            "status": "done",
            "error": "",
            "brief": brief.model_dump(),
            "findings": merged.findings.model_dump(),
            "sources": [{"url": p.url, "title": p.title, "fetched_at": p.fetched_at} for p in crawl.pages],
            "posture": posture.as_dict() if posture else None,
            "completed_at": datetime.utcnow(),
        },
    )
    logger.info(f"[LEAD-RESEARCH] Done contact={contact_id} pages={len(crawl.pages)}")


def _crm_hints(contact: dict) -> str:
    lead = contact.get("lead") or {}
    bits = [
        f"notes: {contact['notes']}" if contact.get("notes") else "",
        f"lead source: {lead['source']}" if lead.get("source") else "",
        f"industry: {lead['industries']}" if lead.get("industries") else "",
        f"employees: {lead['employees_size']}" if lead.get("employees_size") else "",
        f"country: {lead['country']}" if lead.get("country") else "",
    ]
    return "; ".join(b for b in bits if b)


async def _matching_projects(contact: dict, crawl: CrawlResult) -> list[dict]:
    """Past projects for the pitch: the lead's imported-client match if there
    is one, otherwise a match from what their homepage says."""
    try:
        relevant = await get_relevant_projects_for_contact(str(contact["_id"]), contact.get("phone", ""))
        if relevant and relevant.get("projects"):
            return relevant["projects"]
    except Exception as e:
        logger.error(f"[LEAD-RESEARCH] Client project lookup failed error={type(e).__name__}")

    home = crawl.pages[0]
    description = f"{contact.get('company', '')}. {home.description or home.text[:600]}"
    live = await match_projects_from_description(description)
    return live["projects"] if live else []
