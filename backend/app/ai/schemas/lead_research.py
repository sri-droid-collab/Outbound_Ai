from typing import Literal

from pydantic import BaseModel, Field


class PainPoint(BaseModel):
    point: str
    evidence: str = ""
    # Must be one of the collected sources (a fetched page, a news article, the Wikidata entry,
    # or a "dns:<domain>" / "tech:<domain>" pseudo-source); anything else is dropped by ground_brief().
    source_url: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"


class LeadBrief(BaseModel):
    """The call-ready brief a salesperson reads before dialing."""

    company_summary: str = ""
    industry: str = ""
    size_hint: str = ""
    technologies: list[str] = Field(default_factory=list)
    it_posture: str = ""
    pain_points: list[PainPoint] = Field(default_factory=list)
    suggested_opening: str = ""
    discovery_questions: list[str] = Field(default_factory=list)
    objection_prep: list[str] = Field(default_factory=list)
    do_not_say: list[str] = Field(default_factory=list)
    relevant_projects: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


# ---- Collector findings: deterministic facts, each tied to a source. They are stored next to
# the brief and also fed to the model, so the salesperson can check any claim against its source.


class TechFinding(BaseModel):
    name: str
    category: str  # cms, framework, analytics, marketing, support, payments, hosting, server, security
    evidence: str  # what in the page or headers revealed it
    version: str = ""


class JobPosting(BaseModel):
    title: str
    url: str
    it_related: bool = False


class JobsFinding(BaseModel):
    careers_url: str = ""
    postings: list[JobPosting] = Field(default_factory=list)
    it_roles: int = 0
    external_boards: list[str] = Field(default_factory=list)  # job boards we saw links to but don't read


class NewsItem(BaseModel):
    headline: str
    url: str
    publisher: str = ""
    published_at: str = ""  # ISO date, empty when the feed gave none
    tags: list[str] = Field(
        default_factory=list
    )  # funding, acquisition, expansion, leadership, security, ...


class RegistryFacts(BaseModel):
    name: str
    url: str
    description: str = ""
    founded_year: int | None = None
    headquarters: str = ""
    country: str = ""
    industry: str = ""
    employees: int | None = None


class SourceStatus(BaseModel):
    source: str  # site, email_dns, news, registry, tech, jobs
    status: Literal["ok", "empty", "cached", "failed", "skipped"]
    note: str = ""


class ResearchFindings(BaseModel):
    tech: list[TechFinding] = Field(default_factory=list)
    jobs: JobsFinding | None = None
    news: list[NewsItem] = Field(default_factory=list)
    registry: RegistryFacts | None = None
    coverage: list[SourceStatus] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
