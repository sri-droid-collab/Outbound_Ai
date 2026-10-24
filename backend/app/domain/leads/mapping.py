"""Lead <-> contact document mapping.

Three jobs: translate an ERP "Lead" record into the contact shape the call
desk stores, pull the lead attributes out of an imported Excel row, and turn a
partial contact update into a Mongo `$set` that only touches the fields the
client actually sent.
"""

import re

from app.models.schemas import ContactCreate, ContactUpdate, LeadDetails

LEAD_FIELDS = tuple(LeadDetails.model_fields)
MAX_FIELD_CHARS = 200


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _clean_phone(value) -> str:
    """Drop spaces, dashes, dots and brackets but keep a leading '+'. ERP
    numbers are stored with their country code, so nothing is guessed here."""
    s = _text(value)
    if not s:
        return ""
    plus = "+" if s.startswith("+") else ""
    return plus + re.sub(r"\D", "", s)


def _lead_value(field: str, raw) -> str:
    value = _text(raw)[:MAX_FIELD_CHARS]
    # "high" / "HIGH" / "High " all mean the same thing in the table's badge colours.
    return value.title() if field == "priority" else value


def extract_lead_fields(values_by_field: dict) -> dict:
    """The non-empty lead attributes of one imported row, cleaned for storage.
    Over-long values are truncated rather than rejected - an import shouldn't
    drop a whole lead over a long industry description."""
    cleaned = {field: _lead_value(field, values_by_field.get(field)) for field in LEAD_FIELDS}
    return {field: value for field, value in cleaned.items() if value}


def contact_from_erp_lead(erp: dict) -> ContactCreate:
    """Map an ERP Lead record to a ContactCreate.

    Raises ValueError when the record isn't a Lead or has no callable number
    or name - the caller decides whether that skips the row or fails the batch.
    """
    doctype = _text(erp.get("doctype"))
    if doctype and doctype != "Lead":
        raise ValueError(f"Expected a Lead record, got doctype {doctype!r}")

    name = (
        _text(erp.get("lead_name"))
        or " ".join(p for p in (_text(erp.get("first_name")), _text(erp.get("last_name"))) if p)
        or _text(erp.get("title"))
    )
    if not name:
        raise ValueError("Lead has no name (lead_name, first_name/last_name or title)")

    primary = _clean_phone(erp.get("mobile_no")) or _clean_phone(erp.get("phone"))
    if not primary:
        raise ValueError("Lead has no mobile_no or phone")
    other = _clean_phone(erp.get("phone"))
    secondary = other if other and other != primary else ""

    return ContactCreate(
        name=name,
        phone=primary,
        secondary_phone=secondary,
        company=_text(erp.get("company_name")),
        website=_text(erp.get("webpage")),
        lead=LeadDetails.model_validate(extract_lead_fields(erp)),
    )


def contact_update_fields(update: ContactUpdate) -> dict:
    """Build the `$set` document for a partial contact update.

    Top-level fields left as None are skipped (an empty string is a real
    value and clears the field). Lead fields use dotted keys and only the ones
    the client sent, so a form that edits `lead.priority` can't reset
    any other lead attribute.
    """
    fields = {k: v for k, v in update.model_dump(exclude={"lead"}).items() if v is not None}
    if update.lead is not None:
        for key, value in update.lead.model_dump(exclude_unset=True).items():
            fields[f"lead.{key}"] = value
    return fields
