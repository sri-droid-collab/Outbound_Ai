from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.core.timezone import get_request_timezone, to_tz
from app.domain.lead_research import service
from app.models.schemas import LeadResearchResponse, LeadResearchStartRequest, LeadResearchStatusItem

router = APIRouter(prefix="/lead-research", tags=["lead-research"], dependencies=[Depends(get_current_user)])

_DATETIME_FIELDS = ("started_at", "completed_at", "updated_at")


def _serialize(contact_id: str, doc: dict | None, tz_name: str) -> dict:
    if not doc:
        return {"contact_id": contact_id, "status": "none"}
    out = {k: v for k, v in doc.items() if k not in ("_id", "created_at", "requested_by")}
    for key in _DATETIME_FIELDS:
        out[key] = to_tz(out.get(key), tz_name)
    out["sources"] = [
        {**s, "fetched_at": to_tz(s.get("fetched_at"), tz_name)} for s in out.get("sources", [])
    ]
    return out


@router.get("/", response_model=list[LeadResearchStatusItem])
async def list_statuses(tz_name: str = Depends(get_request_timezone)):
    """Status of every researched lead, for the badges on the leads table."""
    return [
        {
            "contact_id": doc["contact_id"],
            "status": doc.get("status", "none"),
            "updated_at": to_tz(doc.get("updated_at"), tz_name),
        }
        for doc in await service.list_research_statuses()
    ]


@router.get("/{contact_id}", response_model=LeadResearchResponse)
async def get_research(contact_id: str, tz_name: str = Depends(get_request_timezone)):
    return _serialize(contact_id, await service.get_research(contact_id), tz_name)


@router.post("/{contact_id}", response_model=LeadResearchResponse, status_code=202)
async def start_research(
    contact_id: str,
    req: LeadResearchStartRequest | None = None,
    tz_name: str = Depends(get_request_timezone),
):
    """Start researching a lead in the background and return its current state.
    Poll GET /lead-research/{contact_id} for progress."""
    try:
        doc = await service.start_research(contact_id, force=bool(req and req.force))
    except service.LeadNotFoundError:
        raise HTTPException(status_code=404, detail="Contact not found") from None
    return _serialize(contact_id, doc, tz_name)
