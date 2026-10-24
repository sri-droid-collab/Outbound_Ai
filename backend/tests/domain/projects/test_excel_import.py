import asyncio
import io
import re

import pytest
from openpyxl import Workbook

from app.domain.projects import excel_import
from app.domain.projects.excel_import import (
    SheetFormatError,
    import_projects,
    normalize_domain,
    parse_projects_workbook,
    split_list,
)

HEADERS = [
    "Project Name",
    "Domain",
    "Related Domains",
    "Summary",
    "Business Problem",
    "Solution Provided",
    "Key Features",
    "Technologies",
    "AI/ML Components",
    "Frontend",
    "Backend",
    "Database",
    "Cloud / DevOps",
]


def _sheet(*rows, headers=HEADERS) -> bytes:
    wb = Workbook()
    wb.active.append(headers)
    for row in rows:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(**fields):
    base = {h: "" for h in HEADERS}
    base.update(fields)
    return [base[h] for h in HEADERS]


class FakeProjectsRepo:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, filter_, **kwargs):
        pattern = filter_["name"]["$regex"]
        return next((d for d in self.docs if re.search(pattern, d.get("name", ""), re.I)), None)

    async def insert_one(self, doc):
        doc["_id"] = f"p{len(self.docs)}"
        self.docs.append(doc)
        return type("Inserted", (), {"inserted_id": doc["_id"]})()

    async def update_one(self, filter_, update, **kwargs):
        doc = next(d for d in self.docs if d["_id"] == filter_["_id"])
        doc.update(update["$set"])


@pytest.fixture
def repo(monkeypatch):
    fake = FakeProjectsRepo()
    refreshed: list[str] = []

    async def fake_refresh(project_id):
        refreshed.append(project_id)

    monkeypatch.setattr(excel_import, "projects_repo", fake)
    monkeypatch.setattr(excel_import, "refresh_matches_for_project", fake_refresh)
    fake.refreshed = refreshed
    return fake


async def _drain():
    await asyncio.sleep(0)  # let the fire-and-forget match refresh run
    await asyncio.sleep(0)


def test_split_list_keeps_separators_inside_parentheses():
    assert split_list("AWS (S3, SQS, Lambda), Redis; Docker\nKubernetes.") == [
        "AWS (S3, SQS, Lambda)",
        "Redis",
        "Docker",
        "Kubernetes",
    ]


def test_split_list_drops_blanks_and_duplicates():
    assert split_list("a, , b,a ,") == ["a", "b"]


def test_split_list_with_only_newlines_and_semicolons_keeps_commas_in_text():
    assert split_list("Fast, cheap and good; Second feature\nThird", separators=";\n") == [
        "Fast, cheap and good",
        "Second feature",
        "Third",
    ]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("healthcare", "Healthcare"),
        ("Retail and E-Commerce", "Retail & E-Commerce"),
        ("  banking & finance ", "Banking & Finance"),
        ("Logistics & Supply Chain", "Logistics & Supply Chain"),
        ("Underwater Basket Weaving", None),
        ("", None),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_full_row_becomes_validated_metadata():
    result = parse_projects_workbook(
        _sheet(
            _row(
                **{
                    "Project Name": "Quadrix AI",
                    "Domain": "logistics & supply chain",
                    "Related Domains": "Retail and E-Commerce, Telecom",
                    "Summary": "Logistics automation.",
                    "Business Problem": "Manual coordination.",
                    "Solution Provided": "AI agents.",
                    "Key Features": "Voice agents\nEmail agent; Doc extraction",
                    "Technologies": "Python, FastAPI, AWS (S3, SQS), Twilio",
                    "AI/ML Components": "Voice agents\nTextract",
                    "Backend": "Python, FastAPI",
                    "Cloud / DevOps": "AWS (S3, SQS)",
                }
            )
        )
    )

    assert result.errors == [] and result.warnings == []
    meta = result.projects[0].metadata
    assert result.projects[0].row == 2 and meta.title == "Quadrix AI"
    assert meta.domain == "Logistics & Supply Chain"
    assert meta.related_domains == ["Retail & E-Commerce", "Telecom"]
    assert meta.key_features == ["Voice agents", "Email agent", "Doc extraction"]
    assert meta.ai_ml_components == ["Voice agents", "Textract"]
    assert meta.tech_stack.backend == ["Python", "FastAPI"]
    assert meta.tech_stack.cloud_devops == ["AWS (S3, SQS)"]
    assert meta.tech_stack.other == ["Twilio"]  # in Technologies but in no group: kept, not lost


def test_flat_technologies_without_groups_leave_the_stack_empty():
    sheet = _sheet(_row(**{"Project Name": "P", "Summary": "s", "Technologies": "Go, Rust"}))

    meta = parse_projects_workbook(sheet).projects[0].metadata

    assert meta.technologies == ["Go", "Rust"]
    assert meta.tech_stack.model_dump() == {
        "frontend": [],
        "backend": [],
        "database": [],
        "cloud_devops": [],
        "other": [],
    }


def test_group_columns_alone_populate_technologies():
    sheet = _sheet(_row(**{"Project Name": "P", "Summary": "s", "Frontend": "React", "Database": "Mongo"}))

    assert parse_projects_workbook(sheet).projects[0].metadata.technologies == ["React", "Mongo"]


def test_unknown_domains_are_saved_as_other_with_a_warning():
    result = parse_projects_workbook(
        _sheet(
            _row(
                **{
                    "Project Name": "P",
                    "Summary": "s",
                    "Domain": "Space Mining",
                    "Related Domains": "Healthcare, Moon",
                }
            )
        )
    )

    assert result.projects[0].metadata.domain == "Other"
    assert result.projects[0].metadata.related_domains == ["Healthcare"]
    assert [w.message for w in result.warnings] == [
        "Unknown domain 'Space Mining' for 'P' - saved as Other",
        "Unknown related domain 'Moon' for 'P' - ignored",
    ]


def test_blank_domain_defaults_to_other_without_a_warning():
    result = parse_projects_workbook(_sheet(_row(**{"Project Name": "P", "Summary": "s"})))

    assert result.projects[0].metadata.domain == "Other" and result.warnings == []


def test_row_problems_are_reported_with_excel_row_numbers_and_blank_rows_skipped():
    result = parse_projects_workbook(
        _sheet(
            _row(**{"Project Name": "Good", "Summary": "s"}),
            _row(),  # blank - ignored, not an error
            _row(**{"Summary": "no name"}),
            _row(**{"Project Name": "Empty Project"}),
        )
    )

    assert [p.name for p in result.projects] == ["Good"]
    assert [(e.row, e.message) for e in result.errors] == [
        (4, "Missing project name"),
        (5, "'Empty Project' needs at least a Summary or Technologies"),
    ]
    assert result.total_rows == 3


def test_header_aliases_are_case_and_punctuation_insensitive():
    result = parse_projects_workbook(
        _sheet(["Alpha", "Does things", "Healthcare"], headers=["PROJECT", "Overview", "Industry"])
    )

    meta = result.projects[0].metadata
    assert meta.summary == "Does things" and meta.domain == "Healthcare"


def test_file_level_problems_raise():
    with pytest.raises(SheetFormatError, match="valid .xlsx"):
        parse_projects_workbook(b"not an excel file")
    with pytest.raises(SheetFormatError, match="Missing required column"):
        parse_projects_workbook(_sheet(["x"], headers=["Summary"]))
    empty = io.BytesIO()
    Workbook().save(empty)
    with pytest.raises(SheetFormatError, match="empty"):
        parse_projects_workbook(empty.getvalue())


async def test_import_creates_finished_projects_and_queues_match_refresh(repo):
    result = await import_projects(
        _sheet(_row(**{"Project Name": "Alpha", "Domain": "Education", "Summary": "s"})), "projects.xlsx"
    )
    await _drain()

    assert (result["imported"], result["updated"], result["skipped"]) == (1, 0, 0)
    doc = repo.docs[0]
    assert doc["processing_status"] == "completed" and doc["source"] == "excel"
    assert doc["file_name"] == "projects.xlsx" and doc["file_path"] == ""
    assert doc["metadata"]["domain"] == "Education"
    assert repo.refreshed == ["p0"]


async def test_reimporting_updates_in_place_instead_of_duplicating(repo):
    await import_projects(_sheet(_row(**{"Project Name": "Alpha", "Summary": "first"})), "a.xlsx")

    result = await import_projects(_sheet(_row(**{"Project Name": "ALPHA", "Summary": "second"})), "b.xlsx")

    assert (result["imported"], result["updated"]) == (0, 1)
    assert len(repo.docs) == 1
    assert repo.docs[0]["metadata"]["summary"] == "second" and repo.docs[0]["file_name"] == "b.xlsx"


async def test_a_project_from_an_uploaded_document_is_never_overwritten(repo):
    repo.docs.append(
        {"_id": "doc1", "name": "Alpha", "file_type": "pdf", "metadata": {"summary": "from the pdf"}}
    )

    result = await import_projects(
        _sheet(_row(**{"Project Name": "Alpha", "Summary": "from excel"})), "a.xlsx"
    )

    assert (result["imported"], result["updated"], result["skipped"]) == (0, 0, 1)
    assert "uploaded document" in result["errors"][0]["message"]
    assert repo.docs[0]["metadata"]["summary"] == "from the pdf"


async def test_name_matching_is_exact_not_a_substring(repo):
    repo.docs.append({"_id": "doc1", "name": "Alpha Beta", "source": "excel", "metadata": {}})

    result = await import_projects(_sheet(_row(**{"Project Name": "Alpha", "Summary": "s"})), "a.xlsx")

    assert result["imported"] == 1 and len(repo.docs) == 2


async def test_regex_characters_in_names_are_treated_literally(repo):
    first = await import_projects(
        _sheet(_row(**{"Project Name": "Eagle-Bot (SAAS)", "Summary": "s"})), "a.xlsx"
    )
    again = await import_projects(
        _sheet(_row(**{"Project Name": "Eagle-Bot (SAAS)", "Summary": "t"})), "a.xlsx"
    )

    assert first["imported"] == 1 and again["updated"] == 1 and len(repo.docs) == 1


async def test_result_reports_warnings_and_skips_without_aborting_the_rest(repo):
    result = await import_projects(
        _sheet(
            _row(**{"Project Name": "Good", "Summary": "s", "Domain": "Mars"}),
            _row(**{"Project Name": "Bad"}),
        ),
        "a.xlsx",
    )

    assert (result["imported"], result["skipped"], result["total_rows"]) == (1, 1, 2)
    assert result["warnings"][0]["row"] == 2 and result["errors"][0]["row"] == 3
