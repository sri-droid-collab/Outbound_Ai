import httpx
import pytest

from app.ai.tools.lead_research.public_api import MAX_BYTES, PublicApiClient, SourceUnavailable

HOST = "api.example.test"


def _client(handler) -> PublicApiClient:
    return PublicApiClient(
        user_agent="OutboundAI-LeadResearch/1.0 (test)",
        timeout=2.0,
        allowed_hosts={HOST},
        transport=httpx.MockTransport(handler),
    )


async def test_get_json_returns_the_payload_and_sends_user_agent_and_params():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        seen["q"] = request.url.params["q"]
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as api:
        data = await api.get_json(f"https://{HOST}/search", {"q": "acme"})

    assert data == {"ok": True}
    assert seen == {"ua": "OutboundAI-LeadResearch/1.0 (test)", "q": "acme"}


async def test_hosts_outside_the_allowlist_are_refused_without_a_request():
    def handler(request):
        raise AssertionError("no request should be made")

    async with _client(handler) as api:
        with pytest.raises(SourceUnavailable, match="host_not_allowed"):
            await api.get_text("https://evil.test/x")


@pytest.mark.parametrize(
    "status, reason",
    [(429, "rate_limited"), (403, "http_403"), (500, "http_500")],
)
async def test_error_statuses_become_short_reasons(status, reason):
    async with _client(lambda r: httpx.Response(status, text="nope")) as api:
        with pytest.raises(SourceUnavailable, match=reason):
            await api.get_text(f"https://{HOST}/x")


async def test_timeouts_and_network_errors_become_short_reasons():
    def timeout(request):
        raise httpx.ReadTimeout("slow")

    def broken(request):
        raise httpx.ConnectError("down")

    async with _client(timeout) as api:
        with pytest.raises(SourceUnavailable, match="timeout"):
            await api.get_text(f"https://{HOST}/x")
    async with _client(broken) as api:
        with pytest.raises(SourceUnavailable, match="network_error"):
            await api.get_text(f"https://{HOST}/x")


async def test_oversized_responses_are_refused():
    async with _client(lambda r: httpx.Response(200, content=b"x" * (MAX_BYTES + 1))) as api:
        with pytest.raises(SourceUnavailable, match="too_large"):
            await api.get_text(f"https://{HOST}/x")


@pytest.mark.parametrize("body", ["not json", "[1, 2, 3]"])
async def test_non_object_json_is_a_bad_response(body):
    async with _client(lambda r: httpx.Response(200, text=body)) as api:
        with pytest.raises(SourceUnavailable, match="bad_response"):
            await api.get_json(f"https://{HOST}/x")


async def test_redirects_are_not_followed():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    async with _client(handler) as api:
        with pytest.raises(SourceUnavailable, match="http_302"):
            await api.get_text(f"https://{HOST}/x")
