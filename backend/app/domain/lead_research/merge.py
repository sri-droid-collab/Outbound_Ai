"""merge_validate: the fan-in after the collectors.

Combines what the collectors found into one `ResearchFindings`, makes sure every fact keeps its
source, turns failed or empty sources into plain-language gaps, and cross-checks facts that
disagree (so the model is told about a conflict instead of silently picking a side).
"""

import re
from dataclasses import dataclass, field

from app.ai.schemas.lead_research import (
    JobsFinding,
    NewsItem,
    RegistryFacts,
    ResearchFindings,
    SourceStatus,
    TechFinding,
)
from app.ai.tools.lead_research.site_crawler import CrawledPage

SOURCE_LABELS = {
    "site": "Website",
    "email_dns": "Email setup (DNS)",
    "news": "News",
    "registry": "Company facts (Wikidata)",
    "tech": "Technology detection",
    "jobs": "Hiring",
}
_CATEGORY_ORDER = [
    "cms",
    "framework",
    "analytics",
    "marketing",
    "support",
    "payments",
    "hosting",
    "server",
    "security",
]
# Wikidata headcounts are often years old; only a large disagreement is worth flagging.
_EMPLOYEE_TOLERANCE = 2


@dataclass
class MergedResearch:
    findings: ResearchFindings
    allowed_sources: set[str] = field(default_factory=set)
    gaps: list[str] = field(default_factory=list)


def parse_employee_range(text: str) -> tuple[int, int | None] | None:
    """'1,001-5,000 employees' -> (1001, 5000); '10,001+ employees' -> (10001, None); None if unparseable."""
    cleaned = text.replace("–", "-")
    span = re.search(r"(\d[\d,]*)\s*(?:-|to)\s*(\d[\d,]*)", cleaned)
    if span:
        return int(span.group(1).replace(",", "")), int(span.group(2).replace(",", ""))
    plus = re.search(r"(\d[\d,]*)\s*\+", cleaned)
    if plus:
        return int(plus.group(1).replace(",", "")), None
    return None


def _employee_conflict(crm_employees: str, registry: RegistryFacts | None) -> str | None:
    if not registry or registry.employees is None or not crm_employees:
        return None
    parsed = parse_employee_range(crm_employees)
    if not parsed:
        return None
    low, high = parsed
    count = registry.employees
    if count * _EMPLOYEE_TOLERANCE < low or (high is not None and count > high * _EMPLOYEE_TOLERANCE):
        return (
            f"Company size disagrees: the lead sheet says '{crm_employees}' but Wikidata lists {count:,} employees "
            "(Wikidata can be out of date) - don't state a headcount as fact."
        )
    return None


def _gap_for(status: SourceStatus) -> str | None:
    label = SOURCE_LABELS.get(status.source, status.source)
    suffix = f" ({status.note})" if status.note else ""
    if status.status == "failed":
        return f"{label}: could not be retrieved{suffix}"
    if status.status == "skipped":
        return f"{label}: not checked{suffix}"
    if status.status == "empty" and status.source in {"news", "registry", "jobs", "tech"}:
        return f"{label}: nothing found{suffix}"
    return None


def _is_http(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def _dedupe_news(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    kept = []
    for item in items:
        if _is_http(item.url) and item.url not in seen:
            seen.add(item.url)
            kept.append(item)
    return kept


def merge_findings(
    *,
    domain: str,
    pages: list[CrawledPage],
    tech: list[TechFinding],
    jobs: JobsFinding | None,
    news: list[NewsItem],
    registry: RegistryFacts | None,
    statuses: list[SourceStatus],
    crm_employees: str = "",
) -> MergedResearch:
    news = _dedupe_news(news)
    tech = sorted(
        tech, key=lambda t: _CATEGORY_ORDER.index(t.category) if t.category in _CATEGORY_ORDER else 99
    )
    conflicts = [c for c in (_employee_conflict(crm_employees, registry),) if c]

    allowed = {p.url for p in pages} | {n.url for n in news}
    if registry:
        allowed.add(registry.url)
    if tech:
        allowed.add(f"tech:{domain}")
    if jobs:
        allowed |= {u for u in (jobs.careers_url, *(p.url for p in jobs.postings)) if u}

    return MergedResearch(
        findings=ResearchFindings(
            tech=tech, jobs=jobs, news=news, registry=registry, coverage=statuses, conflicts=conflicts
        ),
        allowed_sources=allowed,
        gaps=[gap for gap in (_gap_for(s) for s in statuses) if gap],
    )
