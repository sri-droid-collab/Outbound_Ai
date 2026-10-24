import httpx
import pytest

from app.ai.tools.lead_research.public_api import PublicApiClient, SourceUnavailable
from app.ai.tools.lead_research.wikidata import WIKIDATA_HOSTS, lookup_wikidata


def _item(qid):
    return {"mainsnak": {"snaktype": "value", "datavalue": {"value": {"entity-type": "item", "id": qid}}}}


def _entity(
    label, website=None, *, year=None, employees=None, hq=None, industry=None, country=None, description=""
):
    claims = {}
    if website:
        claims["P856"] = [{"mainsnak": {"datavalue": {"value": website}}, "rank": "normal"}]
    if year:
        claims["P571"] = [
            {"mainsnak": {"datavalue": {"value": {"time": f"+{year}-00-00T00:00:00Z"}}}, "rank": "normal"}
        ]
    if employees is not None:
        claims["P1128"] = [
            {"mainsnak": {"datavalue": {"value": {"amount": f"+{employees}"}}}, "rank": "normal"}
        ]
    for prop, qid in (("P159", hq), ("P452", industry), ("P17", country)):
        if qid:
            claims[prop] = [{**_item(qid), "rank": "normal"}]
    return {
        "labels": {"en": {"value": label}},
        "descriptions": {"en": {"value": description}},
        "claims": claims,
    }


def _api(entities, search_ids=None, labels=None, seen=None):
    """A MockTransport behaving like the three Wikidata calls we make."""
    search_ids = list(entities) if search_ids is None else search_ids
    labels = labels or {}

    def handler(request):
        params = request.url.params
        if seen is not None:
            seen.append(dict(params))
        if params["action"] == "wbsearchentities":
            return httpx.Response(200, json={"search": [{"id": q} for q in search_ids]})
        ids = params["ids"].split("|")
        if params["props"] == "labels":
            return httpx.Response(
                200, json={"entities": {q: {"labels": {"en": {"value": labels.get(q, "")}}} for q in ids}}
            )
        return httpx.Response(200, json={"entities": {q: entities[q] for q in ids if q in entities}})

    return PublicApiClient(
        user_agent="OutboundAI-LeadResearch/1.0 (test@example.test)",
        timeout=2.0,
        allowed_hosts=WIKIDATA_HOSTS,
        transport=httpx.MockTransport(handler),
    )


ATLASSIAN = _entity(
    "Atlassian",
    "https://www.atlassian.com/",
    year=2002,
    employees=1100,
    hq="Q1",
    industry="Q2",
    country="Q3",
    description="Australian enterprise software company",
)
LABELS = {"Q1": "Sydney", "Q2": "software industry", "Q3": "Australia"}


async def test_entity_whose_website_matches_is_returned_with_resolved_labels():
    async with _api({"Q757307": ATLASSIAN}, labels=LABELS) as api:
        facts = await lookup_wikidata(api, "Atlassian Pty Ltd", "atlassian.com")

    assert facts.name == "Atlassian"
    assert facts.url == "https://www.wikidata.org/wiki/Q757307"
    assert (facts.founded_year, facts.employees) == (2002, 1100)
    assert (facts.headquarters, facts.industry, facts.country) == ("Sydney", "software industry", "Australia")
    assert facts.description == "Australian enterprise software company"


async def test_a_namesake_with_a_different_website_is_never_used():
    other = _entity("Orion", "https://orion-toys.test/", employees=5)
    async with _api({"Q1": other}) as api:
        assert await lookup_wikidata(api, "Orion", "orion-chat.example") is None


async def test_the_matching_entity_is_picked_from_several_hits():
    entities = {
        "Q10": _entity("Apple Records", "https://applerecords.test/"),
        "Q11": _entity("Apple Inc.", "https://www.apple.com", employees=164000),
    }
    async with _api(entities) as api:
        facts = await lookup_wikidata(api, "Apple", "apple.com")

    assert facts.name == "Apple Inc." and facts.employees == 164000


@pytest.mark.parametrize(
    "site, domain", [("https://shop.acme.com", "acme.com"), ("https://acme.com", "www.acme.com")]
)
async def test_subdomains_and_www_count_as_the_same_site(site, domain):
    async with _api({"Q1": _entity("Acme", site)}) as api:
        assert (await lookup_wikidata(api, "Acme", domain)) is not None


async def test_lookalike_domains_do_not_match():
    async with _api({"Q1": _entity("Acme", "https://notacme.com")}) as api:
        assert await lookup_wikidata(api, "Acme", "acme.com") is None


async def test_no_search_hits_returns_none():
    async with _api({}, search_ids=[]) as api:
        assert await lookup_wikidata(api, "Obscure Local Bakery", "bakery.example") is None


async def test_entity_without_optional_facts_still_returns():
    async with _api({"Q1": _entity("Acme", "https://acme.com")}) as api:
        facts = await lookup_wikidata(api, "Acme", "acme.com")

    assert facts.founded_year is None and facts.employees is None and facts.headquarters == ""


async def test_preferred_statement_wins_over_older_ones():
    entity = _entity("Acme", "https://acme.com", employees=100)
    entity["claims"]["P1128"].append(
        {"mainsnak": {"datavalue": {"value": {"amount": "+250"}}}, "rank": "preferred"}
    )
    async with _api({"Q1": entity}) as api:
        facts = await lookup_wikidata(api, "Acme", "acme.com")

    assert facts.employees == 250


async def test_unusable_company_or_domain_makes_no_request():
    def handler(request):
        raise AssertionError("no request should be made")

    api = PublicApiClient(
        user_agent="t", timeout=2.0, allowed_hosts=WIKIDATA_HOSTS, transport=httpx.MockTransport(handler)
    )
    async with api:
        assert await lookup_wikidata(api, "Co", "acme.com") is None
        assert await lookup_wikidata(api, "Acme", "") is None


async def test_search_uses_the_cleaned_name():
    seen = []
    async with _api({"Q1": ATLASSIAN}, labels=LABELS, seen=seen) as api:
        await lookup_wikidata(api, "Atlassian Pty Ltd", "atlassian.com")

    assert seen[0]["search"] == "Atlassian"  # trailing legal suffixes (Pty Ltd) are stripped


async def test_api_failure_propagates_as_source_unavailable():
    api = PublicApiClient(
        user_agent="t",
        timeout=2.0,
        allowed_hosts=WIKIDATA_HOSTS,
        transport=httpx.MockTransport(lambda r: httpx.Response(403, text="forbidden")),
    )
    async with api:
        with pytest.raises(SourceUnavailable, match="http_403"):
            await lookup_wikidata(api, "Acme", "acme.com")
