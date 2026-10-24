import pytest

from app.ai.tools.lead_research.url_safety import (
    UnsafeUrlError,
    assert_public_url,
    normalize_website,
    site_domain,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("acme.com", "https://acme.com"),
        ("  Acme.COM/about?x=1  ", "https://acme.com"),
        ("http://www.acme.com", "http://www.acme.com"),
        ("https://user:pass@acme.com/x", "https://acme.com"),
        ("https://acme.com:443", "https://acme.com"),
    ],
)
def test_normalize_website_accepts_and_cleans(raw, expected):
    assert normalize_website(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "localhost",
        "intranet",
        "ftp://acme.com",
        "javascript:alert(1)",
        "acme.com:8080",
        "a b.com",
        "https://",
        "http://169.254.169.254",
        "10.0.0.5",
        "http://[::1]",
    ],
)
def test_normalize_website_rejects_non_websites(raw):
    assert normalize_website(raw) is None


def test_site_domain_drops_www():
    assert site_domain("https://www.acme.com") == "acme.com"
    assert site_domain("https://shop.acme.com") == "shop.acme.com"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "ftp://acme.com/",
        "https://acme.com:8080/",
    ],
)
async def test_assert_public_url_blocks_internal_targets(url):
    with pytest.raises(UnsafeUrlError):
        await assert_public_url(url)


async def test_assert_public_url_blocks_hostname_resolving_to_private_address(monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kwargs):
        return [(2, 1, 6, "", ("10.1.2.3", 0))]

    monkeypatch.setattr("asyncio.BaseEventLoop.getaddrinfo", fake_getaddrinfo)

    with pytest.raises(UnsafeUrlError):
        await assert_public_url("https://sneaky.example.com/")


async def test_assert_public_url_blocks_if_any_resolved_address_is_private(monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("asyncio.BaseEventLoop.getaddrinfo", fake_getaddrinfo)

    with pytest.raises(UnsafeUrlError):
        await assert_public_url("https://mixed.example.com/")


async def test_assert_public_url_allows_public_address(monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("asyncio.BaseEventLoop.getaddrinfo", fake_getaddrinfo)

    await assert_public_url("https://acme.com/about")


async def test_assert_public_url_rejects_unresolvable_host(monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kwargs):
        raise OSError("no such host")

    monkeypatch.setattr("asyncio.BaseEventLoop.getaddrinfo", fake_getaddrinfo)

    with pytest.raises(UnsafeUrlError):
        await assert_public_url("https://nope.invalid/")
