import dns.resolver

from app.ai.tools.lead_research.dns_posture import lookup_posture


class _MX:
    def __init__(self, host: str):
        self.exchange = host


class _TXT:
    def __init__(self, text: str):
        self.strings = [text[:10].encode(), text[10:].encode()]  # TXT values arrive split in chunks


class FakeResolver:
    def __init__(self, answers: dict):
        self._answers = answers

    async def resolve(self, name: str, rdtype: str):
        result = self._answers.get((name, rdtype))
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise dns.resolver.NXDOMAIN()
        return result


async def test_google_workspace_with_enforced_dmarc():
    resolver = FakeResolver(
        {
            ("acme.com", "MX"): [_MX("aspmx.l.google.com."), _MX("alt1.aspmx.l.google.com.")],
            ("acme.com", "TXT"): [
                _TXT("google-site-verification=abc"),
                _TXT("v=spf1 include:_spf.google.com ~all"),
            ],
            ("_dmarc.acme.com", "TXT"): [_TXT("v=DMARC1; p=reject; rua=mailto:d@acme.com")],
        }
    )

    posture = await lookup_posture("acme.com", resolver=resolver)

    assert posture.email_provider == "Google Workspace"
    assert posture.mx == ["alt1.aspmx.l.google.com", "aspmx.l.google.com"]
    assert posture.spf.startswith("v=spf1")
    assert posture.dmarc_policy == "reject"


async def test_missing_spf_and_dmarc_are_reported_in_plain_language():
    resolver = FakeResolver({("acme.com", "MX"): [_MX("acme-com.mail.protection.outlook.com.")]})

    posture = await lookup_posture("acme.com", resolver=resolver)
    text = posture.describe()

    assert posture.email_provider == "Microsoft 365"
    assert posture.spf is None and posture.dmarc is None
    assert "SPF record: missing" in text
    assert "DMARC record: missing" in text


async def test_dmarc_policy_none_is_called_out_as_monitoring_only():
    resolver = FakeResolver(
        {
            ("acme.com", "MX"): [_MX("mail.acme.com.")],
            ("_dmarc.acme.com", "TXT"): [_TXT("v=DMARC1; p=none")],
        }
    )

    posture = await lookup_posture("acme.com", resolver=resolver)

    assert posture.email_provider is None
    assert "monitoring only" in posture.describe()
    assert "unknown (MX: mail.acme.com)" in posture.describe()


async def test_gateway_is_identified_before_the_mailbox_provider():
    resolver = FakeResolver({("acme.com", "MX"): [_MX("acme.pphosted.com."), _MX("aspmx.l.google.com.")]})

    assert (
        await lookup_posture("acme.com", resolver=resolver)
    ).email_provider == "Proofpoint (security gateway)"


async def test_dns_failures_never_raise():
    resolver = FakeResolver(
        {("acme.com", "MX"): dns.resolver.LifetimeTimeout(), ("acme.com", "TXT"): dns.resolver.NoAnswer()}
    )

    posture = await lookup_posture("acme.com", resolver=resolver)

    assert posture.mx == [] and posture.spf is None and posture.dmarc is None
    assert "no MX records found" in posture.describe()
