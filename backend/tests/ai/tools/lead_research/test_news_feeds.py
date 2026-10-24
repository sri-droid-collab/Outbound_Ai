import httpx
import pytest

from app.ai.schemas.lead_research import NewsItem
from app.ai.tools.lead_research.news_feeds import (
    NEWS_HOSTS,
    clean_company_name,
    merge_news,
    parse_gdelt,
    parse_google_news_rss,
    search_gdelt,
    search_google_news,
    tag_headline,
)
from app.ai.tools.lead_research.public_api import PublicApiClient, SourceUnavailable

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>feed</title>
<item><title>Acme Robotics raises $40M Series B - TechCrunch</title>
  <link>https://news.google.com/rss/articles/AAA?oc=5</link>
  <pubDate>Wed, 11 Mar 2026 07:00:00 GMT</pubDate><source url="https://techcrunch.com">TechCrunch</source></item>
<item><title>Acme Robotics appoints new CTO</title>
  <link>https://news.google.com/rss/articles/BBB?oc=5</link>
  <pubDate>Mon, 02 Feb 2026 10:00:00 GMT</pubDate><source url="https://example.com">Example Times</source></item>
<item><title>Totally unrelated company news - Daily</title>
  <link>https://news.google.com/rss/articles/CCC</link><pubDate>Mon, 02 Feb 2026 10:00:00 GMT</pubDate></item>
<item><title>Acme Robotics with a javascript link</title><link>javascript:alert(1)</link></item>
<item><title>Acme Robotics undated item</title><link>https://news.google.com/rss/articles/DDD</link></item>
</channel></rss>"""


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Harbor Table Restaurants Pvt Ltd", "Harbor Table Restaurants"),
        ("Acme Robotics, Inc.", "Acme Robotics"),
        ("Soft Suave Technologies Private Limited", "Soft Suave Technologies"),
        ("PetMD", "PetMD"),
        ("Co", ""),
        ("Inc", ""),
        ("", ""),
    ],
)
def test_clean_company_name(raw, expected):
    assert clean_company_name(raw) == expected


@pytest.mark.parametrize(
    "headline, tag",
    [
        ("Acme raises $40M Series B", "funding"),
        ("Giant acquires Acme", "acquisition"),
        ("Acme opens new office in Austin", "expansion"),
        ("Acme appoints new CTO", "leadership"),
        ("Acme confirms ransomware attack", "security"),
        ("Acme announces layoffs", "layoffs"),
        ("Acme partners with Globex", "partnership"),
    ],
)
def test_headline_tags(headline, tag):
    assert tag in tag_headline(headline)


def test_untagged_headline_gets_no_tags():
    assert tag_headline("Acme publishes annual report") == []


def test_rss_items_are_parsed_filtered_and_tidied():
    items = parse_google_news_rss(RSS, "Acme Robotics Inc.")

    assert [i.headline for i in items] == [
        "Acme Robotics raises $40M Series B",  # publisher suffix stripped
        "Acme Robotics appoints new CTO",
        "Acme Robotics undated item",
    ]
    first = items[0]
    assert first.publisher == "TechCrunch" and first.published_at == "2026-03-11"
    assert first.tags == ["funding"]
    assert items[2].published_at == ""


def test_rss_drops_items_that_do_not_name_the_company_or_have_unsafe_links():
    headlines = [i.headline for i in parse_google_news_rss(RSS, "Acme Robotics")]

    assert not any("unrelated" in h for h in headlines)
    assert not any("javascript" in h for h in headlines)


def test_malformed_xml_is_a_bad_response():
    with pytest.raises(SourceUnavailable, match="bad_response"):
        parse_google_news_rss("<rss><channel><item>", "Acme")


def test_xml_entity_bombs_are_rejected_not_expanded():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        "<rss><channel><item><title>&b; Acme</title><link>https://x.test/</link></item></channel></rss>"
    )

    with pytest.raises(SourceUnavailable, match="bad_response"):
        parse_google_news_rss(bomb, "Acme")


def test_a_company_name_too_short_to_search_matches_nothing():
    assert parse_google_news_rss(RSS, "Co") == []
    assert parse_gdelt(GDELT, "Inc") == []


GDELT = {
    "articles": [
        {
            "url": "https://a.test/1",
            "title": "Acme Robotics expands to Berlin",
            "seendate": "20260311T070000Z",
            "domain": "a.test",
        },
        {
            "url": "https://b.test/2",
            "title": "Someone else entirely",
            "seendate": "20260311T070000Z",
            "domain": "b.test",
        },
        {
            "url": "ftp://c.test/3",
            "title": "Acme Robotics bad scheme",
            "seendate": "20260311T070000Z",
            "domain": "c.test",
        },
        {
            "url": "https://d.test/4",
            "title": "Acme Robotics odd date",
            "seendate": "garbage",
            "domain": "d.test",
        },
    ]
}


def test_gdelt_articles_are_parsed_and_filtered():
    items = parse_gdelt(GDELT, "Acme Robotics")

    assert [(i.headline, i.published_at, i.publisher) for i in items] == [
        ("Acme Robotics expands to Berlin", "2026-03-11", "a.test"),
        ("Acme Robotics odd date", "", "d.test"),
    ]
    assert items[0].tags == ["expansion"]


def _news(headline, date="", url=None, **kw):
    return NewsItem(
        headline=headline, url=url or f"https://x.test/{abs(hash(headline))}", published_at=date, **kw
    )


def test_merge_dedupes_across_sources_sorts_newest_first_and_caps():
    google = [_news("Acme raises Series B", "2026-03-11"), _news("Old story", "2025-01-01")]
    gdelt = [_news("ACME raises series b!", "2026-03-10"), _news("Undated", "")]

    merged = merge_news(google, gdelt, limit=3)

    assert [i.headline for i in merged] == ["Acme raises Series B", "Old story", "Undated"]


def test_merge_caps_the_list():
    items = [_news(f"Story {i}", f"2026-01-{i + 1:02d}") for i in range(20)]

    assert len(merge_news(items)) == 8


async def test_google_news_search_quotes_the_cleaned_name_and_limits_to_a_year():
    seen = {}

    def handler(request):
        seen["q"] = request.url.params["q"]
        seen["host"] = request.url.host
        return httpx.Response(200, text=RSS)

    async with PublicApiClient(
        user_agent="t", timeout=2.0, allowed_hosts=NEWS_HOSTS, transport=httpx.MockTransport(handler)
    ) as api:
        items = await search_google_news(api, "Acme Robotics Pvt Ltd")

    assert seen == {"q": '"Acme Robotics" when:1y', "host": "news.google.com"}
    assert len(items) == 3


async def test_gdelt_search_surfaces_rate_limiting_as_unavailable():
    async with PublicApiClient(
        user_agent="t",
        timeout=2.0,
        allowed_hosts=NEWS_HOSTS,
        transport=httpx.MockTransport(lambda r: httpx.Response(429, text="slow down")),
    ) as api:
        with pytest.raises(SourceUnavailable, match="rate_limited"):
            await search_gdelt(api, "Acme Robotics")
