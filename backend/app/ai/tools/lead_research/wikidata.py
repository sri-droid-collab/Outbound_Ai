"""Company facts from Wikidata (founding year, headquarters, industry, headcount).

A name search alone returns the wrong entity as often as the right one ("Orion", "Apple"),
so a result is accepted only when its official website (P856) is the lead's own domain.
Most small companies simply aren't in Wikidata; that returns None, not an error.

Wikidata can also be out of date (headcount especially), so the facts are labelled with
their source and `merge_validate` cross-checks them against what the lead sheet says.
"""

from urllib.parse import urlsplit

from app.ai.schemas.lead_research import RegistryFacts
from app.ai.tools.lead_research.news_feeds import clean_company_name
from app.ai.tools.lead_research.public_api import PublicApiClient

API_URL = "https://www.wikidata.org/w/api.php"
ENTITY_URL = "https://www.wikidata.org/wiki/"
WIKIDATA_HOSTS = {"www.wikidata.org"}

_WEBSITE, _INCEPTION, _HEADQUARTERS, _EMPLOYEES, _INDUSTRY, _COUNTRY = (
    "P856",
    "P571",
    "P159",
    "P1128",
    "P452",
    "P17",
)
_SEARCH_LIMIT = 5


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _same_site(a: str, b: str) -> bool:
    a, b = _host(a) or a.lower().removeprefix("www."), _host(b) or b.lower().removeprefix("www.")
    return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def _statements(entity: dict, prop: str) -> list[dict]:
    """Statements with a real value, preferred-rank ones first."""
    claims = [c for c in entity.get("claims", {}).get(prop, []) if c.get("mainsnak", {}).get("datavalue")]
    return sorted(claims, key=lambda c: c.get("rank") != "preferred")


def _value(entity: dict, prop: str):
    statements = _statements(entity, prop)
    return statements[0]["mainsnak"]["datavalue"]["value"] if statements else None


def _item_id(entity: dict, prop: str) -> str:
    value = _value(entity, prop)
    return value.get("id", "") if isinstance(value, dict) else ""


def _websites(entity: dict) -> list[str]:
    return [s["mainsnak"]["datavalue"]["value"] for s in _statements(entity, _WEBSITE)]


def _year(entity: dict) -> int | None:
    value = _value(entity, _INCEPTION)
    try:
        return int(value["time"][1:5])
    except (TypeError, KeyError, ValueError):
        return None


def _employees(entity: dict) -> int | None:
    value = _value(entity, _EMPLOYEES)
    try:
        return int(float(value["amount"]))
    except (TypeError, KeyError, ValueError):
        return None


async def _labels(api: PublicApiClient, ids: list[str]) -> dict[str, str]:
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    data = await api.get_json(
        API_URL,
        {
            "action": "wbgetentities",
            "ids": "|".join(ids),
            "props": "labels",
            "languages": "en",
            "format": "json",
        },
    )
    return {
        qid: ent.get("labels", {}).get("en", {}).get("value", "")
        for qid, ent in data.get("entities", {}).items()
    }


async def lookup_wikidata(api: PublicApiClient, company: str, domain: str) -> RegistryFacts | None:
    """Facts for the company whose official website is `domain`, or None when there is no safe match."""
    name = clean_company_name(company)
    if not name or not domain:
        return None
    search = await api.get_json(
        API_URL,
        {
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "format": "json",
            "limit": _SEARCH_LIMIT,
        },
    )
    ids = [hit["id"] for hit in search.get("search", []) if hit.get("id")]
    if not ids:
        return None
    entities = (
        await api.get_json(
            API_URL,
            {
                "action": "wbgetentities",
                "ids": "|".join(ids),
                "props": "claims|labels|descriptions",
                "languages": "en",
                "format": "json",
            },
        )
    ).get("entities", {})

    for qid in ids:
        entity = entities.get(qid, {})
        if not any(_same_site(site, domain) for site in _websites(entity)):
            continue
        hq, country, industry = (_item_id(entity, p) for p in (_HEADQUARTERS, _COUNTRY, _INDUSTRY))
        labels = await _labels(api, [hq, country, industry])
        return RegistryFacts(
            name=entity.get("labels", {}).get("en", {}).get("value", name),
            url=f"{ENTITY_URL}{qid}",
            description=entity.get("descriptions", {}).get("en", {}).get("value", ""),
            founded_year=_year(entity),
            headquarters=labels.get(hq, ""),
            country=labels.get(country, ""),
            industry=labels.get(industry, ""),
            employees=_employees(entity),
        )
    return None
