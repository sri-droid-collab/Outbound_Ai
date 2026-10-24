import asyncio
import io
import logging
import re
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.ai.agents.client_domain_agent import enrich_client
from app.core.security import get_current_user
from app.core.timezone import get_request_timezone, to_tz
from app.domain.leads.mapping import extract_lead_fields
from app.domain.spreadsheet import map_headers
from app.models.schemas import ClientResponse, ClientUploadResult
from app.repositories.clients_repo import clients_repo
from app.repositories.contacts_repo import contacts_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["clients"], dependencies=[Depends(get_current_user)])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_ROWS = 1000

# Accepted header spellings, normalized to lowercase alphanumerics.
# The sheet must contain one match for each required field.
HEADER_ALIASES = {
    "name": {"clientname", "leadname", "name", "client", "fullname"},
    "company": {"companydetails", "company", "companyname", "organisation", "organization"},
    "project": {"project", "clientproject", "projectdetails", "projectname"},
    "phone": {"contactnumber", "mobileno", "phone", "phonenumber", "contact", "mobile", "mobilenumber"},
    "secondary_phone": {
        "secondaryphone",
        "secondarynumber",
        "alternatephone",
        "alternatenumber",
        "phone2",
        "contactnumber2",
    },
    # "domain" is deliberately not an alias: in these sheets it usually means
    # the industry, not the web address.
    "website": {"website", "webpage", "companywebsite", "websiteurl", "weburl", "companyurl", "url", "site"},
    # Lead attributes, stored under contact["lead"] (see LeadDetails).
    "industries": {"industries", "industry", "industrytype"},
    "employees_size": {
        "employeessize",
        "employeesize",
        "companysize",
        "employees",
        "noofemployees",
        "headcount",
    },
    "country": {"country"},
    "branch": {"branch"},
    "source": {"source", "leadsource"},
    "priority": {"priority"},
}
REQUIRED_FIELDS = {"name", "phone"}

# Cells that pack more than one number together get split on these.
_PHONE_SPLIT_RE = re.compile(r"[;,\n]+")


def _normalize_phone(value, default_country_code: str = "") -> str:
    s = str(value or "").strip()
    # Excel often stores numbers as floats ("9876543210.0")
    if s.endswith(".0"):
        s = s[:-2]
    digits = re.sub(r"[^\d+]", "", s)
    if not digits:
        return ""
    if digits.startswith("+"):
        return digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if default_country_code:
        cc_digits = default_country_code.lstrip("+")
        # A bare national number (e.g. a 10-digit Indian mobile number) is
        # missing its country code entirely; a number that already starts
        # with the selected country's code and is longer than that already
        # has one, and should only get the "+" rather than a second prefix.
        if digits.startswith(cc_digits) and len(digits) > 10:
            return "+" + digits
        return default_country_code + digits
    # No country selected - best-effort fallback for numbers that already
    # look long enough to include a country code.
    if len(digits) >= 10:
        return "+" + digits
    return digits


def _split_phones(value, default_country_code: str = "") -> list:
    s = str(value or "").strip()
    if not s:
        return []
    parts = [_normalize_phone(p, default_country_code) for p in _PHONE_SPLIT_RE.split(s) if p.strip()]
    return [p for p in parts if p]


def _extract_phones(values_by_field: dict, default_country_code: str = "") -> tuple:
    """Returns (primary, secondary) phone numbers for one row. An explicit
    secondary-phone column always wins; otherwise a second number packed
    into the primary phone cell (e.g. "123, 456") is used as the fallback."""
    phones = _split_phones(values_by_field.get("phone"), default_country_code)
    primary = phones[0] if phones else ""
    secondary = _normalize_phone(values_by_field.get("secondary_phone"), default_country_code) or (
        phones[1] if len(phones) > 1 else ""
    )
    return primary, secondary


def serialize_client(doc, tz_name: str = "UTC") -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "company": doc.get("company", ""),
        "project": doc.get("project", ""),
        "phone": doc.get("phone", ""),
        "contact_id": doc.get("contact_id"),
        "domain": doc.get("domain"),
        "related_domains": doc.get("related_domains", []),
        "matched_project_ids": doc.get("matched_project_ids", []),
        "enrichment_status": doc.get("enrichment_status", "pending"),
        "source_file": doc.get("source_file", ""),
        "created_at": to_tz(doc.get("created_at", datetime.utcnow()), tz_name),
    }


async def _upsert_contact(row: dict) -> str:
    """Create or update the callable contact for an imported client row.
    Existing contacts keep their data — we only fill blanks."""
    existing = await contacts_repo.find_one({"phone": row["phone"]})
    note = f"Client project: {row['project']}" if row["project"] else ""
    secondary_phone = row.get("secondary_phone", "")
    lead = row.get("lead", {})
    if existing:
        update = {}
        if not existing.get("company") and row["company"]:
            update["company"] = row["company"]
        if not existing.get("notes") and note:
            update["notes"] = note
        if not existing.get("secondary_phone") and secondary_phone:
            update["secondary_phone"] = secondary_phone
        if not existing.get("website") and row.get("website"):
            update["website"] = row["website"]
        existing_lead = existing.get("lead") or {}
        for field, value in lead.items():
            if not existing_lead.get(field):
                update[f"lead.{field}"] = value
        if update:
            await contacts_repo.update_one({"_id": existing["_id"]}, {"$set": update})
        return str(existing["_id"])

    result = await contacts_repo.insert_one(
        {
            "name": row["name"],
            "phone": row["phone"],
            "secondary_phone": secondary_phone,
            "company": row["company"],
            "website": row.get("website", ""),
            "status": "new",
            "notes": note,
            "lead": lead,
            "last_called": None,
            "created_at": datetime.utcnow(),
        }
    )
    return str(result.inserted_id)


@router.post("/upload", response_model=ClientUploadResult)
async def upload_clients(file: UploadFile = File(...), country_code: str = Form("")):
    """Import clients from an Excel (.xlsx) file. Each valid row is stored as
    a client, upserted into contacts (so it's immediately callable), and
    queued for AI domain classification + project matching.

    country_code (e.g. "+91") is applied to any phone number that doesn't
    already look international (no "+" / "00" prefix) - without it, a bare
    national number can't be reliably told apart from one that already
    includes a different country's calling code of the same length."""
    country_code = country_code.strip()
    if country_code and not country_code.startswith("+"):
        country_code = "+" + country_code

    filename = file.filename or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "xls":
        raise HTTPException(
            status_code=400,
            detail="Legacy .xls format is not supported. Please save the file as .xlsx and try again.",
        )
    if ext not in ("xlsx", "xlsm"):
        raise HTTPException(status_code=400, detail="Please upload an Excel file (.xlsx).")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 5 MB.")

    try:
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:
        logger.error(f"[CLIENTS] Failed to parse Excel '{filename}': {e}")
        raise HTTPException(status_code=400, detail="Could not read the Excel file. Is it a valid .xlsx?")

    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise HTTPException(status_code=400, detail="The Excel sheet is empty.")

    header_map = map_headers(rows[0], HEADER_ALIASES)
    mapped_fields = set(header_map.values())
    missing = REQUIRED_FIELDS - mapped_fields
    if missing:
        pretty = {"name": "Lead Name", "phone": "Mobile No"}
        raise HTTPException(
            status_code=400,
            detail=f"Missing required column(s): {', '.join(pretty[f] for f in sorted(missing))}. "
            "Required: Lead Name, Mobile No. Optional: Company Name, Webpage, Secondary Phone, Industries, "
            "Employees Size, Country, Branch, Source, Priority, Project.",
        )

    data_rows = []
    for raw in rows[1 : MAX_ROWS + 1]:
        values_by_field = {}
        for idx, field in header_map.items():
            values_by_field[field] = raw[idx] if idx < len(raw) else None
        primary, secondary = _extract_phones(values_by_field, country_code)
        data_rows.append(
            {
                "name": str(values_by_field.get("name") or "").strip(),
                "company": str(values_by_field.get("company") or "").strip(),
                "project": str(values_by_field.get("project") or "").strip(),
                "phone": primary,
                "secondary_phone": secondary,
                "website": str(values_by_field.get("website") or "").strip()[:2000],
                "lead": extract_lead_fields(values_by_field),
            }
        )

    imported = updated = skipped = 0
    errors = []
    new_client_ids = []

    for i, row in enumerate(data_rows, start=2):  # start=2 → Excel row numbers
        if not any(row.values()):
            continue  # blank row
        if not row["name"]:
            skipped += 1
            errors.append({"row": i, "message": "Missing client name"})
            continue
        if not row["phone"] or len(re.sub(r"\D", "", row["phone"])) < 7:
            skipped += 1
            errors.append({"row": i, "message": f"Invalid or missing contact number for '{row['name']}'"})
            continue

        try:
            contact_id = await _upsert_contact(row)
            existing = await clients_repo.find_one({"phone": row["phone"], "project": row["project"]})
            if existing:
                await clients_repo.update_one(
                    {"_id": existing["_id"]},
                    {
                        "$set": {
                            "name": row["name"],
                            "company": row["company"],
                            "contact_id": contact_id,
                            "source_file": filename,
                            "updated_at": datetime.utcnow(),
                        }
                    },
                )
                new_client_ids.append(str(existing["_id"]))
                updated += 1
            else:
                result = await clients_repo.insert_one(
                    {
                        **{
                            k: v for k, v in row.items() if k != "lead"
                        },  # lead attributes live on the contact
                        "contact_id": contact_id,
                        "domain": None,
                        "related_domains": [],
                        "matched_project_ids": [],
                        "enrichment_status": "pending",
                        "source_file": filename,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                )
                new_client_ids.append(str(result.inserted_id))
                imported += 1
        except Exception as e:
            logger.error(f"[CLIENTS] Row {i} failed: {e}")
            skipped += 1
            errors.append({"row": i, "message": "Could not save this row"})

    # Queue AI domain classification + project matching in the background
    for client_id in new_client_ids:
        asyncio.create_task(enrich_client(client_id))

    logger.info(f"[CLIENTS] Imported '{filename}': {imported} new, {updated} updated, {skipped} skipped")
    return {
        "total_rows": imported + updated + skipped,
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:20],
    }


@router.get("/", response_model=list[ClientResponse])
async def get_clients(tz_name: str = Depends(get_request_timezone)):
    clients = []
    async for doc in clients_repo.find().sort("created_at", -1):
        clients.append(serialize_client(doc, tz_name))
    return clients


@router.delete("/{client_id}")
async def delete_client(client_id: str):
    if not ObjectId.is_valid(client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    result = await clients_repo.delete_one({"_id": ObjectId(client_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"message": "Client deleted"}
