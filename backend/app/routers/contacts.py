from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.core.timezone import get_request_timezone, to_tz
from app.domain.leads.mapping import contact_update_fields
from app.models.schemas import ContactCreate, ContactResponse, ContactUpdate
from app.repositories.contacts_repo import contacts_repo

router = APIRouter(prefix="/contacts", tags=["contacts"], dependencies=[Depends(get_current_user)])


def serialize_contact(doc, tz_name: str = "UTC") -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "phone": doc["phone"],
        "secondary_phone": doc.get("secondary_phone", ""),
        "company": doc.get("company", ""),
        "website": doc.get("website", ""),
        "status": doc.get("status", "new"),
        "notes": doc.get("notes", ""),
        "lead": doc.get("lead") or {},
        "last_called": to_tz(doc.get("last_called"), tz_name),
        "assigned_to": doc.get("assigned_to"),
        "created_at": to_tz(doc.get("created_at", datetime.utcnow()), tz_name),
    }


@router.get("/", response_model=list[ContactResponse])
async def get_contacts(tz_name: str = Depends(get_request_timezone)):
    contacts = []
    async for doc in contacts_repo.find().sort("created_at", -1):
        contacts.append(serialize_contact(doc, tz_name))
    return contacts


@router.post("/", response_model=ContactResponse)
async def create_contact(contact: ContactCreate, tz_name: str = Depends(get_request_timezone)):
    doc = {
        **contact.model_dump(),
        "last_called": None,
        "created_at": datetime.utcnow(),
    }
    result = await contacts_repo.insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize_contact(doc, tz_name)


@router.put("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: str, contact: ContactUpdate, tz_name: str = Depends(get_request_timezone)
):
    update_data = contact_update_fields(contact)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await contacts_repo.find_one_and_update(
        {"_id": ObjectId(contact_id)},
        {"$set": update_data},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Contact not found")
    return serialize_contact(result, tz_name)


@router.delete("/{contact_id}")
async def delete_contact(contact_id: str):
    result = await contacts_repo.delete_one({"_id": ObjectId(contact_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"message": "Contact deleted"}
