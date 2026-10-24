from typing import Literal

from pydantic import BaseModel, Field


class PainPoint(BaseModel):
    point: str
    evidence: str = ""
    # Must be one of the pages we actually fetched (or "dns:<domain>" for the
    # email-setup check); anything else is dropped by ground_brief().
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
