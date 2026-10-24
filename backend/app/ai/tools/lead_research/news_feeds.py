"""Recent news about a company from free, keyless feeds.

Google News RSS is the primary source. GDELT is an optional extra (it rate-limits hard).
Headlines are filtered to ones that actually name the company and tagged by simple keyword
rules (funding, acquisition, expansion, ...), so the tags can be trusted and explained.
"""

import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree

from app.ai.schemas.lead_research import NewsItem
from app.ai.tools.lead_research.public_api import PublicApiClient, SourceUnavailable

GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWS_HOSTS = {"news.google.com", "api.gdeltproject.org"}

MAX_FEED_ITEMS = 40  # a feed can return ~100; the newest relevant few are enough
MAX_NEWS_ITEMS = 8

_LEGAL_SUFFIXES = {
    "inc", "llc", "llp", "ltd", "limited", "pvt", "private", "corp", "corporation", "co", "company",
    "gmbh", "plc", "pte", "pty", "sa", "ag", "bv", "nv", "lp",
}  # fmt: skip

_TAG_RULES = {
    "funding": r"\b(raises?|raised|funding|series [a-e]\b|seed round|investment|invests?|investors?|valuation|ipo)\b",
    "acquisition": r"\b(acquires?|acquired|acquisition|merger|merges?|buys?|buyout|takeover)\b",
    "expansion": r"\b(expands?|expansion|opens?|new office|new headquarters|launches?|launched|enters?)\b",
    "leadership": r"\b(appoints?|appointed|names?|new (ceo|cto|cio|ciso|cfo|coo)|steps down|resigns?|hires?|joins as)\b",
    "security": r"\b(breach|ransomware|hack(ed|ers?)?|cyber ?attack|data leak|vulnerabilit(y|ies)|outage)\b",
    "layoffs": r"\b(layoffs?|lays off|job cuts?|cuts? jobs|restructuring|downsiz\w+)\b",
    "partnership": r"\b(partners?|partnership|teams up|collaborat\w+|alliance)\b",
}
_TAG_PATTERNS = {tag: re.compile(pattern, re.I) for tag, pattern in _TAG_RULES.items()}


def clean_company_name(name: str) -> str:
    """'Harbor Table Restaurants Pvt Ltd' -> 'Harbor Table Restaurants'. Empty when too short to search."""
    words = re.sub(r"[,()]", " ", name or "").split()
    while words and words[-1].lower().strip(".") in _LEGAL_SUFFIXES:
        words.pop()
    cleaned = " ".join(words).strip()
    return cleaned if len(cleaned) >= 3 else ""


def tag_headline(headline: str) -> list[str]:
    return [tag for tag, pattern in _TAG_PATTERNS.items() if pattern.search(headline)]


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _iso_date_from_rfc822(value: str) -> str:
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse_google_news_rss(xml: str, company: str) -> list[NewsItem]:
    """Items from a Google News RSS document whose headline names the company."""
    try:
        root = ElementTree.fromstring(xml)
    except (ElementTree.ParseError, ValueError) as e:
        raise SourceUnavailable("bad_response") from e
    name = clean_company_name(company).lower()
    if not name:
        return []  # an empty name is "contained" in every headline
    items: list[NewsItem] = []
    for item in root.findall("./channel/item")[:MAX_FEED_ITEMS]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        publisher = (source_el.text or "").strip() if source_el is not None else ""
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(f" - {publisher}")].rstrip()
        if not title or not link.startswith(("http://", "https://")) or name not in title.lower():
            continue
        items.append(
            NewsItem(
                headline=title,
                url=link,
                publisher=publisher,
                published_at=_iso_date_from_rfc822(item.findtext("pubDate") or ""),
                tags=tag_headline(title),
            )
        )
    return items


def parse_gdelt(payload: dict, company: str) -> list[NewsItem]:
    name = clean_company_name(company).lower()
    if not name:
        return []
    items: list[NewsItem] = []
    for article in payload.get("articles", [])[:MAX_FEED_ITEMS]:
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not title or not url.startswith(("http://", "https://")) or name not in title.lower():
            continue
        try:
            published = datetime.strptime(article.get("seendate", ""), "%Y%m%dT%H%M%SZ").date().isoformat()
        except ValueError:
            published = ""
        items.append(
            NewsItem(
                headline=title,
                url=url,
                publisher=article.get("domain", ""),
                published_at=published,
                tags=tag_headline(title),
            )
        )
    return items


def merge_news(*groups: list[NewsItem], limit: int = MAX_NEWS_ITEMS) -> list[NewsItem]:
    """Dedupe by headline, newest first (undated last), capped."""
    seen: set[str] = set()
    merged: list[NewsItem] = []
    for group in groups:
        for item in group:
            key = _normalize(item.headline)
            if key not in seen:
                seen.add(key)
                merged.append(item)
    merged.sort(key=lambda i: i.published_at or "", reverse=True)
    return merged[:limit]


async def search_google_news(api: PublicApiClient, company: str) -> list[NewsItem]:
    name = clean_company_name(company)
    xml = await api.get_text(
        GOOGLE_NEWS_URL, {"q": f'"{name}" when:1y', "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )
    return parse_google_news_rss(xml, company)


async def search_gdelt(api: PublicApiClient, company: str) -> list[NewsItem]:
    name = clean_company_name(company)
    payload = await api.get_json(
        GDELT_URL,
        {
            "query": f'"{name}"',
            "mode": "artlist",
            "format": "json",
            "maxrecords": 15,
            "timespan": "12months",
            "sort": "datedesc",
        },
    )
    return parse_gdelt(payload, company)
