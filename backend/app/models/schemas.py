from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated, Any, Literal, Optional
from datetime import datetime
from enum import Enum

from app.ai.schemas.lead_research import LeadBrief

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
UrlText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ContactStatus(str, Enum):
    new = "new"
    called = "called"
    follow_up = "follow_up"
    closed = "closed"


class LeadDetails(BaseModel):
    """Lead attributes beyond the call-desk basics, stored under `contact["lead"]`.
    Only what the lead sheet carries and the call or research uses - the CRM's
    own workflow fields (owner, assignment, status, follow-up ids) stay in the CRM."""

    industries: ShortText = ""
    employees_size: ShortText = ""
    country: ShortText = ""
    branch: ShortText = ""
    source: ShortText = ""
    priority: ShortText = ""


class ContactCreate(BaseModel):
    name: str
    phone: str
    secondary_phone: str = ""
    company: str = ""
    website: UrlText = ""
    status: ContactStatus = ContactStatus.new
    notes: str = ""
    lead: LeadDetails = Field(default_factory=LeadDetails)


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    secondary_phone: Optional[str] = None
    company: Optional[str] = None
    website: UrlText | None = None
    status: Optional[ContactStatus] = None
    notes: Optional[str] = None
    # Only the lead fields actually sent are written (see
    # domain.leads.mapping.contact_update_fields), so editing a few fields
    # never wipes the rest of the ERP-owned data.
    lead: LeadDetails | None = None


class ContactResponse(BaseModel):
    id: str
    name: str
    phone: str
    secondary_phone: str = ""
    company: str
    website: str = ""
    status: ContactStatus
    notes: str
    lead: LeadDetails = Field(default_factory=LeadDetails)
    last_called: Optional[datetime] = None
    assigned_to: Optional[str] = None
    created_at: datetime


class CallInitiateRequest(BaseModel):
    contact_id: str
    phone: str


class CallLogResponse(BaseModel):
    id: str
    contact_id: str
    contact_name: str
    phone: str
    status: str
    duration: int = 0
    transcript: str = ""
    suggestions: list[Any] = []
    analysis: Optional[dict] = None
    user_id: Optional[str] = None
    created_at: datetime


class EnrichmentStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ClientResponse(BaseModel):
    id: str
    name: str
    company: str = ""
    project: str = ""
    phone: str
    contact_id: Optional[str] = None
    domain: Optional[str] = None
    related_domains: list[str] = []
    matched_project_ids: list[str] = []
    enrichment_status: EnrichmentStatus = EnrichmentStatus.pending
    source_file: str = ""
    created_at: datetime


class ClientUploadRowError(BaseModel):
    row: int
    message: str


class ClientUploadResult(BaseModel):
    total_rows: int
    imported: int
    updated: int
    skipped: int
    errors: list[ClientUploadRowError] = []


class ProjectImportResult(BaseModel):
    total_rows: int
    imported: int
    updated: int
    skipped: int
    errors: list[ClientUploadRowError] = []
    warnings: list[ClientUploadRowError] = []  # imported, but something was adjusted (e.g. unknown domain)


class ProcessingStatus(str, Enum):
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ProjectResponse(BaseModel):
    id: str
    name: str
    file_name: str
    file_type: str
    file_size: int = 0
    processing_status: ProcessingStatus
    processing_error: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime


class UserRole(str, Enum):
    admin = "admin"
    sales = "sales"


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: UserRole = UserRole.sales


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class AssignedNumberSummary(BaseModel):
    id: str
    phone_number: str
    label: str = ""


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: UserRole
    is_active: bool
    assigned_numbers: list[AssignedNumberSummary] = []
    created_at: datetime


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TwilioNumberCreate(BaseModel):
    phone_number: str
    label: str = ""


class TwilioNumberUpdate(BaseModel):
    label: Optional[str] = None
    is_active: Optional[bool] = None


class TwilioNumberAssign(BaseModel):
    user_id: str
    action: Literal["add", "remove"] = "add"


class AssignedUserSummary(BaseModel):
    id: str
    name: str


class TwilioNumberResponse(BaseModel):
    id: str
    phone_number: str
    label: str = ""
    is_active: bool
    assigned_users: list[AssignedUserSummary] = []
    created_at: datetime


class LeadResearchStartRequest(BaseModel):
    force: bool = False  # re-run even when a fresh brief exists


class ResearchStep(BaseModel):
    name: str
    status: Literal["pending", "running", "done", "failed"] = "pending"


class ResearchSource(BaseModel):
    url: str
    title: str = ""
    fetched_at: datetime | None = None


class LeadResearchResponse(BaseModel):
    contact_id: str
    status: Literal["none", "needs_website", "queued", "running", "done", "failed"] = "none"
    website: str = ""
    steps: list[ResearchStep] = []
    error: str = ""
    brief: LeadBrief | None = None
    sources: list[ResearchSource] = []
    posture: dict | None = None
    is_stale: bool = False  # the brief is older than the cache window
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime | None = None


class LeadResearchStatusItem(BaseModel):
    contact_id: str
    status: str
    updated_at: datetime | None = None
