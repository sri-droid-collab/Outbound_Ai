import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core.security import get_current_user
from app.domain.projects import excel_import
from app.routers import projects
from tests.domain.projects.test_excel_import import FakeProjectsRepo

SAMPLE = Path(__file__).resolve().parents[2] / "scripts" / "sample_projects.xlsx"


@pytest.fixture
def env(monkeypatch):
    repo = FakeProjectsRepo()

    async def no_refresh(project_id):
        return None

    monkeypatch.setattr(excel_import, "projects_repo", repo)
    monkeypatch.setattr(excel_import, "refresh_matches_for_project", no_refresh)
    app = FastAPI()
    app.include_router(projects.router)
    app.dependency_overrides[get_current_user] = lambda: {"_id": "u1", "role": "admin"}
    return TestClient(app), repo


def _post(client, content: bytes, name: str = "projects.xlsx"):
    return client.post("/projects/import-excel", files={"file": (name, content, "application/octet-stream")})


def _xlsx(*rows) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sample_projects_sheet_imports_cleanly(env):
    client, repo = env

    resp = _post(client, SAMPLE.read_bytes(), "sample_projects.xlsx")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["imported"], body["updated"], body["skipped"]) == (11, 0, 0)
    assert body["errors"] == [] and body["warnings"] == []
    assert {d["metadata"]["domain"] for d in repo.docs} >= {
        "Healthcare",
        "Retail & E-Commerce",
        "Logistics & Supply Chain",
        "Education",
        "Travel & Hospitality",
        "Other",
    }
    assert all(d["processing_status"] == "completed" for d in repo.docs)


def test_importing_the_sample_twice_updates_instead_of_duplicating(env):
    client, repo = env
    _post(client, SAMPLE.read_bytes())

    body = _post(client, SAMPLE.read_bytes()).json()

    assert (body["imported"], body["updated"]) == (0, 11)
    assert len(repo.docs) == 11


def test_imported_project_has_the_fields_the_ui_shows(env):
    client, repo = env
    _post(client, SAMPLE.read_bytes())

    quadrix = next(d for d in repo.docs if d["name"] == "Quadrix AI")["metadata"]

    assert quadrix["domain"] == "Logistics & Supply Chain"
    assert quadrix["summary"] and quadrix["business_problem"] and quadrix["solution_provided"]
    assert len(quadrix["key_features"]) >= 3 and quadrix["ai_ml_components"]
    assert "FastAPI" in quadrix["tech_stack"]["backend"]
    assert "Twilio" in quadrix["tech_stack"]["other"]


@pytest.mark.parametrize(
    "name, content, fragment",
    [
        ("projects.xls", b"x", "Legacy .xls"),
        ("projects.csv", b"x", "Excel file"),
        ("projects.xlsx", b"", "empty"),
        ("projects.xlsx", b"not excel", "valid .xlsx"),
    ],
)
def test_bad_uploads_get_a_400_with_a_reason(env, name, content, fragment):
    client, _ = env

    resp = _post(client, content, name)

    assert resp.status_code == 400 and fragment in resp.json()["detail"]


def test_wrong_columns_name_what_is_needed(env):
    client, _ = env

    resp = _post(client, _xlsx(["Summary"], ["x"]))

    assert resp.status_code == 400
    assert "Project Name" in resp.json()["detail"]


def test_oversized_files_are_rejected(env):
    client, _ = env

    resp = _post(client, b"x" * (5 * 1024 * 1024 + 1))

    assert resp.status_code == 400 and "too large" in resp.json()["detail"]


def test_endpoint_requires_authentication():
    app = FastAPI()
    app.include_router(projects.router)

    anonymous = TestClient(app).post("/projects/import-excel", files={"file": ("p.xlsx", b"x")})

    assert anonymous.status_code in (401, 403)
