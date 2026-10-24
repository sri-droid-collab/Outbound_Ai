import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core.security import get_current_user
from app.routers import clients

SAMPLE = Path(__file__).resolve().parents[2] / "scripts" / "sample_leads.xlsx"


class _Inserted:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeRepo:
    """In-memory collection supporting equality filters and $set (including dotted keys)."""

    def __init__(self):
        self.docs: list[dict] = []

    async def find_one(self, filter_, **kwargs):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in filter_.items())), None)

    async def insert_one(self, doc):
        doc["_id"] = f"id{len(self.docs)}"
        self.docs.append(doc)
        return _Inserted(doc["_id"])

    async def update_one(self, filter_, update, **kwargs):
        doc = next(d for d in self.docs if d["_id"] == filter_["_id"])
        for key, value in update["$set"].items():
            target = doc
            *parents, leaf = key.split(".")
            for part in parents:
                target = target.setdefault(part, {})
            target[leaf] = value


@pytest.fixture
def env(monkeypatch):
    contacts, client_docs = FakeRepo(), FakeRepo()
    queued = []

    async def fake_enrich(client_id):
        queued.append(client_id)

    monkeypatch.setattr(clients, "contacts_repo", contacts)
    monkeypatch.setattr(clients, "clients_repo", client_docs)
    monkeypatch.setattr(clients, "enrich_client", fake_enrich)

    app = FastAPI()
    app.include_router(clients.router)
    app.dependency_overrides[get_current_user] = lambda: {"_id": "u1", "role": "admin"}
    return TestClient(app), contacts, client_docs, queued


def _upload(client, content: bytes, country_code: str = ""):
    return client.post(
        "/clients/upload",
        files={"file": ("leads.xlsx", content, "application/octet-stream")},
        data={"country_code": country_code},
    )


def _sheet(*rows) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sample_sheet_imports_with_the_documented_counts(env):
    client, contacts, client_docs, queued = env

    resp = _upload(client, SAMPLE.read_bytes())

    assert resp.status_code == 200
    body = resp.json()
    assert (body["imported"], body["updated"], body["skipped"]) == (10, 1, 2)
    assert body["errors"] == [
        {"row": 9, "message": "Invalid or missing contact number for 'No Number Lead'"},
        {"row": 10, "message": "Missing client name"},
    ]
    assert len(contacts.docs) == 10
    assert len(queued) == 11  # every imported or updated row is queued for enrichment


def test_lead_fields_land_on_the_contact(env):
    client, contacts, *_ = env
    _upload(client, SAMPLE.read_bytes())

    techila = next(c for c in contacts.docs if c["name"] == "Techila Global Services")

    assert techila["phone"] == "+12125550101"
    assert techila["website"] == "https://techilaservices.com/"
    assert techila["company"] == "Techila Global Services"
    assert techila["lead"] == {
        "industries": "IT Services and IT Consulting",
        "employees_size": "1,001-5,000 employees",
        "country": "India",
        "branch": "Chennai",
        "source": "Linkedin-Sales",
        "priority": "High",
    }


def test_priority_case_is_normalised_and_two_numbers_in_one_cell_are_split(env):
    client, contacts, *_ = env
    _upload(client, SAMPLE.read_bytes())

    priya = next(c for c in contacts.docs if c["name"] == "Priya Raman")
    meera = next(c for c in contacts.docs if c["name"] == "Meera Iyer")

    assert priya["lead"]["priority"] == "Medium"  # sheet says "medium"
    assert meera["phone"] == "+12125550104" and meera["secondary_phone"] == "+12125550114"
    assert meera["lead"]["priority"] == "High"  # sheet says "HIGH"


def test_reimporting_a_known_phone_fills_blanks_without_overwriting(env):
    client, contacts, *_ = env
    _upload(client, SAMPLE.read_bytes())
    priya = next(c for c in contacts.docs if c["name"] == "Priya Raman")
    assert priya["lead"]["employees_size"] == "51-200 employees"

    resp = _upload(
        client,
        _sheet(
            ["Lead Name", "Mobile No", "Employees Size", "Country", "Branch", "Project"],
            [
                "Priya R.",
                "+1 212 555 0102",
                "5,000+ employees",
                "Canada",
                "Mumbai",
                "Pet health records assistant",
            ],
        ),
    )

    assert resp.json()["updated"] == 1
    assert priya["lead"]["employees_size"] == "51-200 employees"  # existing value kept
    assert priya["lead"]["country"] == "United States"
    assert priya["name"] == "Priya Raman"


def test_blank_lead_cells_leave_the_contact_without_lead_data(env):
    client, contacts, *_ = env

    _upload(client, _sheet(["Lead Name", "Mobile No", "Country"], ["Solo Lead", "+1 212 555 0150", ""]))

    assert contacts.docs[0]["lead"] == {}


def test_lead_attributes_are_not_copied_into_the_clients_collection(env):
    client, _contacts, client_docs, _queued = env

    _upload(client, SAMPLE.read_bytes())

    assert client_docs.docs and all("lead" not in d for d in client_docs.docs)


def test_legacy_headers_still_work(env):
    client, contacts, *_ = env

    resp = _upload(
        client,
        _sheet(
            ["Client Name", "Company Details", "Project", "Contact Number"],
            ["Old Format", "Legacy Ltd", "CRM revamp", "+1 212 555 0160"],
        ),
    )

    assert resp.json()["imported"] == 1
    assert contacts.docs[0]["company"] == "Legacy Ltd"
    assert contacts.docs[0]["notes"] == "Client project: CRM revamp"


def test_missing_required_columns_names_what_is_needed(env):
    client, *_ = env

    resp = _upload(client, _sheet(["Company Name", "Country"], ["Acme", "India"]))

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "Lead Name" in detail and "Mobile No" in detail
