"""IT hiring signals from a company's careers pages.

Works on pages the crawler already read. Job titles are recognised by shape (a short line with a
role word in it), so this only sees listings that are in the page HTML; boards that load via
JavaScript or live on an external applicant-tracking site are reported as such rather than guessed.
"""

import re
from urllib.parse import urlsplit

from app.ai.schemas.lead_research import JobPosting, JobsFinding
from app.ai.tools.lead_research.site_crawler import CrawledPage

MAX_POSTINGS = 20

_CAREERS_PATH = re.compile(
    r"/(careers?|jobs?|join(-us)?|work-with-us|openings?|vacanc\w*|opportunit\w*)(/|$)", re.I
)
_ROLE_WORDS = re.compile(
    r"\b(engineer|developer|architect|analyst|administrator|devops|sre|scientist|designer|consultant|"
    r"specialist|technician|manager|director|officer|tester|qa|programmer|intern|lead|admin)\b",
    re.I,
)
_IT_WORDS = re.compile(
    r"\b(software|developer|devops|sre|cloud|data|machine learning|ml|ai|security|network|systems?|it|qa|"
    r"test(er|ing)?|platform|back-?end|front-?end|full[- ]stack|database|dba|infrastructure|sysadmin|"
    r"help ?desk|python|java|react|node|\.net|aws|azure|gcp|kubernetes|sql|oracle|sap|salesforce|snowflake|admin)\b",
    re.I,
)
_JOB_LINK = re.compile(r"/(jobs?|positions?|openings?|apply|careers?)/[^/]+", re.I)
_ATS_HOSTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com", "bamboohr.com",
    "myworkdayjobs.com", "jobvite.com", "recruitee.com", "breezy.hr", "icims.com", "teamtailor.com",
)  # fmt: skip


def _is_careers_page(page: CrawledPage) -> bool:
    return bool(_CAREERS_PATH.search(urlsplit(page.url).path + "/"))


def _looks_like_title(line: str) -> bool:
    words = line.split()
    return (
        6 <= len(line) <= 80
        and 2 <= len(words) <= 10
        and not line.endswith((".", ":", "?", "!"))
        and bool(_ROLE_WORDS.search(line))
    )


def _ats_boards(pages: list[CrawledPage]) -> list[str]:
    boards: list[str] = []
    for page in pages:
        for url, _ in page.links:
            host = (urlsplit(url).hostname or "").lower()
            match = next((h for h in _ATS_HOSTS if host == h or host.endswith("." + h)), None)
            if match and match not in boards:
                boards.append(match)
    return boards


_LEADING_CODE = re.compile(r"^[A-Za-z]{1,4}-?\d{3,}\s*")
_TRAILING_NUMBER = re.compile(r"\s*\(\d+\)\s*$")


def _clean_title(text: str) -> str:
    """'JB001984 Integration Tester (2804)' -> 'Integration Tester': drop requisition codes and counters."""
    return " ".join(_TRAILING_NUMBER.sub("", _LEADING_CODE.sub("", text)).split())


def _posting_url(page: CrawledPage, title: str) -> str:
    """The link to this posting when the page has one (its anchor text contains the title), else the page."""
    wanted = title.lower()
    for url, anchor in page.links:
        if wanted in anchor.lower() and _JOB_LINK.search(urlsplit(url).path):
            return url
    return page.url


def find_jobs(pages: list[CrawledPage]) -> JobsFinding | None:
    """IT-related openings found on careers pages, or None when there is no careers page or board at all."""
    careers = [p for p in pages if _is_careers_page(p)]
    boards = _ats_boards(pages)
    if not careers and not boards:
        return None

    postings: dict[str, JobPosting] = {}

    def add(title: str, url: str) -> None:
        if title and title.lower() not in postings:
            postings[title.lower()] = JobPosting(
                title=title, url=url, it_related=bool(_IT_WORDS.search(title))
            )

    for page in careers:
        # Job boards are usually a grid of card links whose fields (code, title, location, type) are
        # sibling elements, so the card's own text pieces are the reliable source: take the first
        # piece shaped like a job title. The page's flat text is useless for these (it is one glued line).
        for url, anchor in page.links:
            if not _JOB_LINK.search(urlsplit(url).path):
                continue
            for piece in anchor.split("\n"):
                title = _clean_title(piece)
                if _looks_like_title(title):
                    add(title, url)
                    break
        # Plain lists of titles (no links) are read from the page's text lines instead.
        for line in page.text.split("\n"):
            title = _clean_title(line.strip())
            if _looks_like_title(title):
                add(title, _posting_url(page, title))

    ordered = sorted(postings.values(), key=lambda p: not p.it_related)[:MAX_POSTINGS]
    return JobsFinding(
        careers_url=careers[0].url if careers else "",
        postings=ordered,
        it_roles=sum(1 for p in ordered if p.it_related),
        external_boards=boards,
    )
