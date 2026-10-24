import pytest
from pydantic import ValidationError

from app.domain.leads.mapping import (
    contact_from_erp_lead,
    contact_update_fields,
    extract_lead_fields,
)
from app.models.schemas import ContactCreate, ContactUpdate, LeadDetails

ERP_LEAD = {
    "doctype": "Lead",
    "name": "Techila Global Services",
    "title": "Techila Global Services",
    "first_name": "Techila",
    "middle_name": "Global",
    "last_name": "Services",
    "lead_name": "Techila Global Services",
    "company_name": "Techila Global Services",
    "entity_type": "Organization",
    "lead_type": "Individual",
    "no_of_employees": "1-10",
    "employees_size": "1,001-5,000 employees",
    "industries": "IT Services and IT Consulting",
    "webpage": "https://techilaservices.com/",
    "mobile_no": "+1 561-220-0044",
    "phone": "+1 561-220-0044",
    "branch": "Chennai",
    "country": "India",
    "company": "Soft Suave Technologies Private Limited",
    "source": "Linkedin-Sales",
    "custom_lead_from": "sscoldleads@gmail.com",
    "status": "Converted",
    "lead_status": "Lead",
    "monitor_lead_status": "Converted",
    "qualification_status": "Unqualified",
    "priority": "High",
    "created_date": "2024-10-29",
    "lead_owner": "kirthika.delli@softsuave.com",
    "assigned_to": "suresh.v@softsuave.com",
    "is_lead_assigned": 1,
    "follow_up_process": "FU-LEAD-24-00015",
}


def test_erp_lead_maps_desk_fields():
    contact = contact_from_erp_lead(ERP_LEAD)

    assert contact.name == "Techila Global Services"
    assert contact.phone == "+15612200044"
    assert contact.secondary_phone == ""  # ERP phone == mobile_no, so nothing extra to keep
    assert contact.company == "Techila Global Services"
    assert contact.website == "https://techilaservices.com/"
    assert contact.status.value == "new"  # the CRM's "Converted" is not the call-desk status


def test_erp_lead_keeps_only_the_required_lead_fields():
    lead = contact_from_erp_lead(ERP_LEAD).lead

    assert lead == LeadDetails(
        industries="IT Services and IT Consulting",
        employees_size="1,001-5,000 employees",
        country="India",
        branch="Chennai",
        source="Linkedin-Sales",
        priority="High",
    )
    # CRM workflow fields and the contradicting no_of_employees are deliberately not carried over
    assert set(LeadDetails.model_fields) == {
        "industries",
        "employees_size",
        "country",
        "branch",
        "source",
        "priority",
    }


def test_distinct_phone_becomes_secondary():
    contact = contact_from_erp_lead({**ERP_LEAD, "phone": "+91 44 2345 6789"})

    assert contact.phone == "+15612200044"
    assert contact.secondary_phone == "+914423456789"


def test_falls_back_to_phone_when_no_mobile():
    contact = contact_from_erp_lead({**ERP_LEAD, "mobile_no": "", "phone": "+1 (561) 220-0044"})

    assert contact.phone == "+15612200044"
    assert contact.secondary_phone == ""


def test_name_falls_back_to_first_and_last_then_title():
    no_lead_name = {**ERP_LEAD, "lead_name": ""}
    assert contact_from_erp_lead(no_lead_name).name == "Techila Services"

    only_title = {**no_lead_name, "first_name": "", "last_name": ""}
    assert contact_from_erp_lead(only_title).name == "Techila Global Services"


@pytest.mark.parametrize(
    "broken, message",
    [
        ({"doctype": "Customer"}, "Expected a Lead"),
        ({"mobile_no": "", "phone": ""}, "no mobile_no or phone"),
        ({"lead_name": "", "first_name": "", "last_name": "", "title": ""}, "no name"),
    ],
)
def test_unusable_records_are_rejected(broken, message):
    with pytest.raises(ValueError, match=message):
        contact_from_erp_lead({**ERP_LEAD, **broken})


def test_extract_lead_fields_skips_blanks_and_normalizes_priority():
    row = {"industries": "  Robotics ", "country": None, "priority": "hIGH", "branch": "", "name": "ignored"}

    assert extract_lead_fields(row) == {"industries": "Robotics", "priority": "High"}


def test_extract_lead_fields_truncates_instead_of_rejecting():
    fields = extract_lead_fields({"industries": "x" * 500})

    assert len(fields["industries"]) == 200
    LeadDetails.model_validate(fields)  # still valid for storage


def test_direct_construction_still_rejects_oversized_values():
    with pytest.raises(ValidationError):
        LeadDetails(branch="x" * 201)


def test_contact_defaults_have_empty_lead():
    contact = ContactCreate(name="A", phone="+911234567890")

    assert contact.lead == LeadDetails()
    assert contact.website == ""


def test_update_only_writes_lead_fields_that_were_sent():
    update = ContactUpdate.model_validate({"notes": "hi", "lead": {"priority": "Low", "source": ""}})

    assert contact_update_fields(update) == {
        "notes": "hi",
        "lead.priority": "Low",
        "lead.source": "",  # an explicit empty string clears the field
    }


def test_update_skips_unset_top_level_fields_but_keeps_empty_strings():
    update = ContactUpdate.model_validate({"secondary_phone": "", "website": " https://acme.com "})

    assert contact_update_fields(update) == {"secondary_phone": "", "website": "https://acme.com"}


def test_update_without_lead_never_touches_lead():
    fields = contact_update_fields(ContactUpdate.model_validate({"company": "Acme"}))

    assert fields == {"company": "Acme"}
