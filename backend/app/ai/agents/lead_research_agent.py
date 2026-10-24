"""Lead research agent: turns what the collectors found into a call-ready brief.

It never fetches anything and never touches the database - the domain service
hands it the evidence and persists the result. Its one quality gate is
`ground_brief`, which drops any claim that doesn't trace to a collected source.
"""

import logging
from dataclasses import dataclass, field

from app.ai.prompts.lead_research_prompts import (
    build_brief_messages,
    build_projects_block,
    build_sources_block,
)
from app.ai.providers.factory import get_provider
from app.ai.schemas.lead_research import LeadBrief
from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ResearchEvidence:
    contact_name: str
    company: str
    website: str
    domain: str
    crm_hints: str = ""
    pages: list[dict] = field(default_factory=list)  # {url, title, description, text}
    email_setup: str | None = None
    projects: list[dict] = field(default_factory=list)


def _model_for(provider) -> str:
    settings = get_settings()
    return settings.groq_model if provider.name == "groq" else settings.openai_model


def _url_key(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/").lower()


def ground_brief(brief: LeadBrief, evidence: ResearchEvidence) -> tuple[LeadBrief, int]:
    """Remove pain points that cite a URL we never fetched and project
    recommendations that aren't in our portfolio. Returns the cleaned brief and
    how many claims were dropped (also noted in `gaps` so the rep can see it)."""
    allowed = {_url_key(p["url"]) for p in evidence.pages}
    if evidence.email_setup:
        allowed.add(_url_key(f"dns:{evidence.domain}"))
    kept = [p for p in brief.pain_points if _url_key(p.source_url) in allowed]
    dropped = len(brief.pain_points) - len(kept)

    names = [p["name"].lower() for p in evidence.projects]
    projects = [r for r in brief.relevant_projects if any(n in r.lower() for n in names)]
    dropped += len(brief.relevant_projects) - len(projects)

    cleaned = brief.model_copy(update={"pain_points": kept, "relevant_projects": projects})
    if dropped:
        cleaned.gaps = [
            *cleaned.gaps,
            f"{dropped} unsupported claim(s) were removed because they didn't trace to a source",
        ]
    return cleaned, dropped


async def generate_brief(evidence: ResearchEvidence, provider_name: str | None = None) -> LeadBrief:
    provider = get_provider(provider_name)
    messages = build_brief_messages(
        contact_name=evidence.contact_name,
        company=evidence.company,
        website=evidence.website,
        crm_hints=evidence.crm_hints,
        sources_block=build_sources_block(evidence.pages, evidence.email_setup, evidence.domain),
        projects_block=build_projects_block(evidence.projects),
    )
    brief = await provider.complete_structured(
        messages, LeadBrief, model=_model_for(provider), temperature=0.2, max_tokens=1800
    )
    grounded, dropped = ground_brief(brief, evidence)
    logger.info(f"[LEAD-RESEARCH] Brief generated domain={evidence.domain} dropped_claims={dropped}")
    return grounded
