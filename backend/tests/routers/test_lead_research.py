from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.domain.lead_research import service
from app.routers import lead_research

CONTACT_ID = "507f1f77bcf86cd799439011"


def _doc(**overrides):
    base = {
        "_id": "mongo-internal-id",
        "contact_id": CONTACT_ID,
        "status": "queued",
        "website": "https://acme.com",
        "steps": [{"name": "fetch_site", "status": "pending"}],
        "error": "",
        "started_at": datetime(2026, 10, 24, 10, 0, 0),
        "completed_at": None,
        "updated_at": datetime(2026, 10, 24, 10, 0, 0),
        "created_at": datetime(2026, 10, 24, 10, 0, 0),
        "is_stale": False,
    }
    return {**base, **overrides}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(lead_research.router)
    app.dependency_overrides[get_current_user] = lambda: {"_id": "u1", "role": "sales"}
    return TestClient(app)


def test_start_returns_202_with_the_run_state(client, monkeypatch):
    seen = {}

    async def fake_start(contact_id, force=False):
        seen.update(contact_id=contact_id, force=force)
        return _doc()

    monkeypatch.setattr(service, "start_research", fake_start)

    resp = client.post(
        f"/lead-research/{CONTACT_ID}", json={"force": True}, headers={"X-Timezone": "Asia/Kolkata"}
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["steps"] == [{"name": "fetch_site", "status": "pending"}]
    assert body["started_at"].endswith("+05:30")  # converted to the caller's timezone
    assert "_id" not in body and "created_at" not in body
    assert seen == {"contact_id": CONTACT_ID, "force": True}


def test_start_without_a_body_defaults_to_no_force(client, monkeypatch):
    seen = {}

    async def fake_start(contact_id, force=False):
        seen["force"] = force
        return _doc()

    monkeypatch.setattr(service, "start_research", fake_start)

    assert client.post(f"/lead-research/{CONTACT_ID}").status_code == 202
    assert seen["force"] is False


def test_start_for_unknown_contact_is_404(client, monkeypatch):
    async def fake_start(contact_id, force=False):
        raise service.LeadNotFoundError(contact_id)

    monkeypatch.setattr(service, "start_research", fake_start)

    assert client.post(f"/lead-research/{CONTACT_ID}").status_code == 404


def test_get_for_unresearched_contact_reports_status_none(client, monkeypatch):
    async def fake_get(contact_id):
        return None

    monkeypatch.setattr(service, "get_research", fake_get)

    resp = client.get(f"/lead-research/{CONTACT_ID}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "none"


def test_get_returns_the_brief(client, monkeypatch):
    async def fake_get(contact_id):
        return _doc(
            status="done",
            brief={
                "company_summary": "Acme builds robots.",
                "pain_points": [{"point": "p", "source_url": "https://acme.com/"}],
            },
            sources=[
                {"url": "https://acme.com/", "title": "Acme", "fetched_at": datetime(2026, 10, 24, 10, 1)}
            ],
            posture={"email_provider": "Google Workspace"},
            completed_at=datetime(2026, 10, 24, 10, 2),
        )

    monkeypatch.setattr(service, "get_research", fake_get)

    body = client.get(f"/lead-research/{CONTACT_ID}").json()

    assert body["status"] == "done"
    assert body["brief"]["company_summary"] == "Acme builds robots."
    assert body["brief"]["pain_points"][0]["confidence"] == "medium"  # schema default applied
    assert body["sources"][0]["url"] == "https://acme.com/"


def test_list_statuses(client, monkeypatch):
    async def fake_list():
        return [{"contact_id": CONTACT_ID, "status": "running", "updated_at": datetime(2026, 10, 24, 10, 0)}]

    monkeypatch.setattr(service, "list_research_statuses", fake_list)

    items = client.get("/lead-research/").json()

    assert [(i["contact_id"], i["status"]) for i in items] == [(CONTACT_ID, "running")]
    assert items[0]["updated_at"].startswith("2026-10-24T10:00:00")


def test_endpoints_require_authentication():
    app = FastAPI()
    app.include_router(lead_research.router)  # no dependency override

    anonymous = TestClient(app)

    assert anonymous.get(f"/lead-research/{CONTACT_ID}").status_code in (401, 403)
    assert anonymous.post(f"/lead-research/{CONTACT_ID}").status_code in (401, 403)
    assert anonymous.get("/lead-research/").status_code in (401, 403)
