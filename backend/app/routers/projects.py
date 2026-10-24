import asyncio
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.ai.agents.project_extraction_agent import process_project
from app.ai.schemas.project_extraction import CANONICAL_DOMAINS
from app.core.security import get_current_user
from app.core.timezone import get_request_timezone, to_tz
from app.domain.projects.excel_import import SheetFormatError, import_projects
from app.models.schemas import ProjectImportResult, ProjectResponse
from app.repositories.clients_repo import clients_repo
from app.repositories.projects_repo import projects_repo
from app.services.document_service import ALLOWED_EXTENSIONS, MAX_FILE_SIZE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(get_current_user)])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "projects"
MAX_EXCEL_SIZE = 5 * 1024 * 1024  # 5 MB


def serialize_project(doc, tz_name: str = "UTC") -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "file_name": doc.get("file_name", ""),
        "file_type": doc.get("file_type", ""),
        "file_size": doc.get("file_size", 0),
        "processing_status": doc.get("processing_status", "processing"),
        "processing_error": doc.get("processing_error"),
        "metadata": doc.get("metadata"),
        "created_at": to_tz(doc.get("created_at", datetime.utcnow()), tz_name),
    }


@router.post("/upload", response_model=ProjectResponse)
async def upload_project(file: UploadFile = File(...), tz_name: str = Depends(get_request_timezone)):
    """Upload a project document (PDF/Word). Text extraction and AI analysis
    run in the background — poll GET /projects/ for processing_status."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or 'unknown'}'. Allowed: PDF, DOC, DOCX.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 20 MB.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", file.filename or f"project{ext}")
    file_path = UPLOAD_DIR / f"{uuid.uuid4().hex[:12]}_{safe_name}"
    file_path.write_bytes(content)

    doc = {
        "name": Path(file.filename or safe_name).stem.replace("_", " ").replace("-", " ").strip(),
        "file_name": file.filename or safe_name,
        "file_type": ext.lstrip("."),
        "file_size": len(content),
        "file_path": str(file_path),
        "extracted_text": "",
        "processing_status": "processing",
        "processing_error": None,
        "metadata": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = await projects_repo.insert_one(doc)
    doc["_id"] = result.inserted_id

    asyncio.create_task(process_project(str(result.inserted_id)))
    logger.info(f"[PROJECTS] Uploaded '{doc['file_name']}' → processing started")
    return serialize_project(doc, tz_name)


@router.post("/import-excel", response_model=ProjectImportResult)
async def import_projects_excel(file: Annotated[UploadFile, File()]):
    """Import projects from an Excel sheet (one project per row). Imported
    projects are ready immediately - no AI processing step."""
    filename = file.filename or "projects.xlsx"
    ext = Path(filename).suffix.lower()
    if ext == ".xls":
        raise HTTPException(
            status_code=400,
            detail="Legacy .xls format is not supported. Please save the file as .xlsx and try again.",
        )
    if ext not in (".xlsx", ".xlsm"):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx).")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > MAX_EXCEL_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 5 MB.")

    try:
        return await import_projects(content, filename)
    except SheetFormatError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/", response_model=list[ProjectResponse])
async def get_projects(tz_name: str = Depends(get_request_timezone)):
    projects = []
    async for doc in projects_repo.find().sort("created_at", -1):
        projects.append(serialize_project(doc, tz_name))
    return projects


@router.get("/graph")
async def get_knowledge_graph():
    """Projects grouped by domain — powers the knowledge map."""
    domains: dict = {}
    async for doc in projects_repo.find({"processing_status": "completed"}).sort("created_at", -1):
        meta = doc.get("metadata", {}) or {}
        domain = meta.get("domain") or "Other"
        domains.setdefault(domain, []).append(
            {
                "id": str(doc["_id"]),
                "name": doc.get("name", ""),
                "summary": meta.get("summary", ""),
                "technologies": meta.get("technologies", [])[:6],
                "related_domains": meta.get("related_domains", []),
                "has_ai": bool(meta.get("ai_ml_components")),
            }
        )

    ordered = [d for d in CANONICAL_DOMAINS if d in domains]
    return {"domains": [{"domain": d, "count": len(domains[d]), "projects": domains[d]} for d in ordered]}


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, tz_name: str = Depends(get_request_timezone)):
    if not ObjectId.is_valid(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    doc = await projects_repo.find_one({"_id": ObjectId(project_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found")
    return serialize_project(doc, tz_name)


@router.post("/{project_id}/reprocess", response_model=ProjectResponse)
async def reprocess_project(project_id: str, tz_name: str = Depends(get_request_timezone)):
    """Retry AI processing for a failed (or stuck) project."""
    if not ObjectId.is_valid(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    doc = await projects_repo.find_one_and_update(
        {"_id": ObjectId(project_id)},
        {"$set": {"processing_status": "processing", "processing_error": None}},
        return_document=True,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found")
    asyncio.create_task(process_project(project_id))
    return serialize_project(doc, tz_name)


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    if not ObjectId.is_valid(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    doc = await projects_repo.find_one_and_delete({"_id": ObjectId(project_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found")

    # Remove the stored file and any client references to this project
    try:
        # Excel-imported projects have no stored file (empty path, not a real one).
        path = Path(doc["file_path"]) if doc.get("file_path") else None
        if path and path.exists():
            path.unlink()
    except OSError as e:
        logger.warning(f"[PROJECTS] Could not delete file for {project_id}: {e}")
    await clients_repo.update_many(
        {"matched_project_ids": project_id},
        {"$pull": {"matched_project_ids": project_id}},
    )
    return {"message": "Project deleted"}
