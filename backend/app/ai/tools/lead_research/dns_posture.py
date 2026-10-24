"""Email setup facts from public DNS: who hosts their mail, and whether SPF
and DMARC are in place. Pure lookups - nothing is sent to the company."""

import asyncio
import re
from dataclasses import asdict, dataclass, field

import dns.asyncresolver
import dns.exception

LOOKUP_TIMEOUT_SECONDS = 5.0

# MX host suffix -> provider label. Order matters: first match wins.
_MAIL_PROVIDERS = [
    ("pphosted.com", "Proofpoint (security gateway)"),
    ("mimecast.com", "Mimecast (security gateway)"),
    ("google.com", "Google Workspace"),
    ("googlemail.com", "Google Workspace"),
    ("protection.outlook.com", "Microsoft 365"),
    ("outlook.com", "Microsoft 365"),
    ("zoho.com", "Zoho Mail"),
    ("zoho.in", "Zoho Mail"),
    ("secureserver.net", "GoDaddy mail"),
]


@dataclass
class DnsPosture:
    domain: str
    mx: list[str] = field(default_factory=list)
    spf: str | None = None
    dmarc: str | None = None
    dmarc_policy: str | None = None  # none | quarantine | reject
    email_provider: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        """Plain-language facts for the brief prompt."""
        if self.email_provider:
            provider = self.email_provider
        elif self.mx:
            provider = f"unknown (MX: {', '.join(self.mx)})"
        else:
            provider = "no MX records found"
        lines = [f"Mail provider: {provider}"]
        lines.append("SPF record: present" if self.spf else "SPF record: missing")
        if not self.dmarc:
            lines.append("DMARC record: missing")
        elif self.dmarc_policy == "none":
            lines.append(
                "DMARC record: present but policy is p=none (monitoring only, spoofed mail is not blocked)"
            )
        else:
            lines.append(f"DMARC record: present, policy p={self.dmarc_policy or 'unspecified'}")
        return "\n".join(lines)


def _provider_for(mx_hosts: list[str]) -> str | None:
    for host in mx_hosts:
        for suffix, label in _MAIL_PROVIDERS:
            if host.endswith(suffix):
                return label
    return None


def _default_resolver():
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = LOOKUP_TIMEOUT_SECONDS
    return resolver


async def _query(resolver, name: str, rdtype: str) -> list:
    try:
        return list(await resolver.resolve(name, rdtype))
    except dns.exception.DNSException:
        return []  # NXDOMAIN, no answer, timeout: all mean "nothing usable here"


def _txt_records(answers: list) -> list[str]:
    return [b"".join(r.strings).decode("utf-8", errors="replace") for r in answers]


async def lookup_posture(domain: str, resolver=None) -> DnsPosture:
    """Never raises: failed lookups just leave fields empty."""
    resolver = resolver or _default_resolver()
    mx_answers, txt_answers, dmarc_answers = await asyncio.gather(
        _query(resolver, domain, "MX"),
        _query(resolver, domain, "TXT"),
        _query(resolver, f"_dmarc.{domain}", "TXT"),
    )
    mx = sorted({str(r.exchange).rstrip(".").lower() for r in mx_answers if str(r.exchange).strip(".")})
    spf = next((t for t in _txt_records(txt_answers) if t.lower().startswith("v=spf1")), None)
    dmarc = next((t for t in _txt_records(dmarc_answers) if t.lower().startswith("v=dmarc1")), None)
    policy_match = re.search(r"\bp=(none|quarantine|reject)\b", dmarc or "", re.I)
    return DnsPosture(
        domain=domain,
        mx=mx,
        spf=spf,
        dmarc=dmarc,
        dmarc_policy=policy_match.group(1).lower() if policy_match else None,
        email_provider=_provider_for(mx),
    )
