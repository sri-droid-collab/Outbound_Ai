from datetime import datetime

from app.ai.tools.lead_research.job_signals import MAX_POSTINGS, find_jobs
from app.ai.tools.lead_research.site_crawler import CrawledPage


def _page(url, text="", links=()):
    return CrawledPage(
        url=url, title="", description="", text=text, fetched_at=datetime.utcnow(), links=list(links)
    )


CAREERS_TEXT = """Join our team
Open positions
Senior Backend Engineer
DevOps Engineer (AWS)
Customer Success Manager
We are a fast growing company that builds great products for logistics teams worldwide.
Data Scientist
Office Manager
Search jobs"""


def test_it_roles_are_found_and_ranked_first():
    jobs = find_jobs([_page("https://acme.com/", "Home"), _page("https://acme.com/careers", CAREERS_TEXT)])

    titles = [p.title for p in jobs.postings]
    assert jobs.careers_url == "https://acme.com/careers"
    assert titles[:3] == ["Senior Backend Engineer", "DevOps Engineer (AWS)", "Data Scientist"]
    assert set(titles[3:]) == {"Customer Success Manager", "Office Manager"}
    assert jobs.it_roles == 3
    assert all(p.it_related for p in jobs.postings[:3]) and not any(p.it_related for p in jobs.postings[3:])


def test_navigation_and_marketing_lines_are_not_mistaken_for_jobs():
    jobs = find_jobs([_page("https://acme.com/careers", CAREERS_TEXT)])

    titles = {p.title for p in jobs.postings}
    assert not titles & {"Join our team", "Open positions", "Search jobs"}
    assert not any("fast growing" in t for t in titles)


def test_anchors_that_point_at_a_posting_carry_the_posting_url():
    page = _page(
        "https://acme.com/careers",
        links=[
            ("https://acme.com/careers/senior-sre", "Site Reliability Engineer"),
            ("https://acme.com/about", "About us"),
            ("https://acme.com/careers", "Careers"),
        ],
    )

    jobs = find_jobs([page])

    assert [(p.title, p.url) for p in jobs.postings] == [
        ("Site Reliability Engineer", "https://acme.com/careers/senior-sre")
    ]


def test_text_found_on_the_page_uses_the_page_url():
    jobs = find_jobs([_page("https://acme.com/jobs", "Data Engineer")])

    assert jobs.postings[0].url == "https://acme.com/jobs"


def test_no_careers_page_and_no_job_board_is_none():
    assert (
        find_jobs([_page("https://acme.com/", "Home"), _page("https://acme.com/about", "Software Engineer")])
        is None
    )


def test_external_job_boards_are_reported_even_without_a_careers_page():
    home = _page(
        "https://acme.com/",
        links=[("https://boards.greenhouse.io/acme", "Join us"), ("https://jobs.lever.co/acme", "Jobs")],
    )

    jobs = find_jobs([home])

    assert jobs.postings == [] and jobs.careers_url == ""
    assert jobs.external_boards == ["greenhouse.io", "lever.co"]


def test_careers_page_with_no_readable_listings_still_reports_the_page():
    jobs = find_jobs([_page("https://acme.com/careers", "Careers\nWe are hiring!")])

    assert jobs.careers_url == "https://acme.com/careers" and jobs.postings == []


def test_lookalike_hosts_are_not_job_boards():
    home = _page("https://acme.com/", links=[("https://notgreenhouse.io/x", "Jobs")])

    assert find_jobs([home]) is None


def test_postings_are_deduplicated_and_capped():
    text = "\n".join(f"Software Engineer {i}" for i in range(50)) + "\nSoftware Engineer 1"

    jobs = find_jobs([_page("https://acme.com/careers", text)])

    assert len(jobs.postings) == MAX_POSTINGS
    assert len({p.title.lower() for p in jobs.postings}) == MAX_POSTINGS


REAL_BOARD_CARDS = [
    # Shaped like a real careers grid: each card is one link whose fields are sibling elements.
    (
        "https://acme.com/careers/1",
        "JB001986\nSri Ranjini_Data Scientist and React\nBangalore · Hybrid\nFull-time",
    ),
    ("https://acme.com/careers/2", "JB001985\nDell Bhoomi\nPan India · Hybrid\nFull-time"),
    ("https://acme.com/careers/3", "JB001984\nIntegration Tester (2804)\nPan India · Remote\nFull-time"),
    ("https://acme.com/careers/4", "JB001983\nPeoplesoft Developer\nBangalore, Mumbai · Hybrid\nFull-time"),
    ("https://acme.com/careers/5", "JB001981\nSnowflake Admin\nPan India · Hybrid\nFull-time"),
]
# ...while the page's flat text is a single glued line, which must not be mistaken for a title.
GLUED_TEXT = "".join(a.replace("\n", "") for _, a in REAL_BOARD_CARDS)


def test_card_links_yield_clean_titles_and_their_own_urls():
    jobs = find_jobs([_page("https://acme.com/careers", GLUED_TEXT, REAL_BOARD_CARDS)])

    assert {(p.title, p.url) for p in jobs.postings} == {
        ("Sri Ranjini_Data Scientist and React", "https://acme.com/careers/1"),
        ("Integration Tester", "https://acme.com/careers/3"),
        ("Peoplesoft Developer", "https://acme.com/careers/4"),
        ("Snowflake Admin", "https://acme.com/careers/5"),
    }  # "Dell Bhoomi" has no role word, so it isn't taken for a job title
    assert jobs.it_roles == 4


def test_no_location_or_employment_type_leaks_into_a_title():
    jobs = find_jobs([_page("https://acme.com/careers", GLUED_TEXT, REAL_BOARD_CARDS)])

    for posting in jobs.postings:
        assert not any(
            junk in posting.title for junk in ("Hybrid", "Remote", "Full-time", "Pan India", "JB00")
        )


def test_a_title_present_as_both_a_card_and_a_text_line_is_listed_once_with_the_card_url():
    page = _page(
        "https://acme.com/careers",
        text="Senior Backend Engineer\nRemote",
        links=[("https://acme.com/careers/1", "Senior Backend Engineer\nRemote\nFull-time")],
    )

    jobs = find_jobs([page])

    assert [(p.title, p.url) for p in jobs.postings] == [
        ("Senior Backend Engineer", "https://acme.com/careers/1")
    ]


def test_requisition_codes_and_counters_are_stripped_from_titles():
    jobs = find_jobs(
        [_page("https://acme.com/careers", "JB001986 Data Scientist (12)\nREQ-4471 DevOps Engineer")]
    )

    assert {p.title for p in jobs.postings} == {"Data Scientist", "DevOps Engineer"}
