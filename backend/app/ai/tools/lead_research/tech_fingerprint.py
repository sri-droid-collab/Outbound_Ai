"""What a company's website is built on, read from its homepage HTML and response headers.

Our own small signature table instead of a third-party fingerprinting library: the signals are
deterministic and each finding says what revealed it, so a salesperson (or the model) can check it.
Versions are reported only when the site itself discloses them.
"""

import re

from app.ai.schemas.lead_research import TechFinding

MAX_FINDINGS = 25

# (name, category, lowercase substrings that appear in the page source)
_HTML_SIGNATURES = [
    ("WordPress", "cms", ("/wp-content/", "/wp-includes/")),
    ("Shopify", "cms", ("cdn.shopify.com", "shopify.theme")),
    ("Wix", "cms", ("static.wixstatic.com", "wix.com website builder")),
    ("Squarespace", "cms", ("static1.squarespace.com", "squarespace.com/")),
    ("Webflow", "cms", ("assets.website-files.com", "webflow.com")),
    ("Drupal", "cms", ("/sites/default/files/", "drupal-settings-json")),
    ("Joomla", "cms", ("/media/jui/", "/components/com_")),
    ("Next.js", "framework", ("/_next/static/", "__next_data__")),
    ("Nuxt", "framework", ("/_nuxt/", "__nuxt__")),
    ("Gatsby", "framework", ("/page-data/", "___gatsby")),
    ("Angular", "framework", ("ng-version=", "ng-app")),
    ("React", "framework", ("data-reactroot", "react-dom")),
    ("Vue.js", "framework", ("data-v-app", "vue.js", "/vue.")),
    ("jQuery", "framework", ("jquery",)),
    ("Bootstrap", "framework", ("bootstrap.min.css", "bootstrap.bundle")),
    ("Google Tag Manager", "analytics", ("googletagmanager.com/gtm.js",)),
    ("Google Analytics", "analytics", ("google-analytics.com/", "googletagmanager.com/gtag/js")),
    ("Hotjar", "analytics", ("static.hotjar.com",)),
    ("Segment", "analytics", ("cdn.segment.com",)),
    ("HubSpot", "marketing", ("js.hs-scripts.com", "js.hs-analytics.net", "hubspot.com/")),
    ("Marketo", "marketing", ("munchkin.marketo.net",)),
    ("Meta Pixel", "marketing", ("connect.facebook.net/",)),
    ("LinkedIn Insight", "marketing", ("snap.licdn.com",)),
    ("Intercom", "support", ("widget.intercom.io", "intercomcdn.com")),
    ("Drift", "support", ("js.driftt.com",)),
    ("Zendesk", "support", ("static.zdassets.com", "zendesk.com/")),
    ("Freshdesk", "support", ("freshdesk.com", "freshchat")),
    ("Stripe", "payments", ("js.stripe.com",)),
    ("PayPal", "payments", ("paypal.com/sdk", "paypalobjects.com")),
    ("reCAPTCHA", "security", ("google.com/recaptcha", "gstatic.com/recaptcha")),
    ("Cloudflare Turnstile", "security", ("challenges.cloudflare.com/turnstile",)),
]

# (name, category, header name, lowercase substring in its value; "" = header presence is enough)
_HEADER_SIGNATURES = [
    ("Cloudflare", "hosting", "cf-ray", ""),
    ("Cloudflare", "hosting", "server", "cloudflare"),
    ("Vercel", "hosting", "x-vercel-id", ""),
    ("Netlify", "hosting", "x-nf-request-id", ""),
    ("AWS CloudFront", "hosting", "x-amz-cf-id", ""),
    ("AWS CloudFront", "hosting", "via", "cloudfront"),
    ("Fastly", "hosting", "x-served-by", "cache-"),
    ("GitHub Pages", "hosting", "x-github-request-id", ""),
    ("Azure Front Door", "hosting", "x-azure-ref", ""),
    ("Akamai", "hosting", "server", "akamai"),
    ("Sucuri", "security", "x-sucuri-id", ""),
]

_GENERATOR = re.compile(r"""<meta[^>]+name=["']generator["'][^>]+content=["']([^"']+)["']""", re.I)
_GENERATOR_ALT = re.compile(r"""<meta[^>]+content=["']([^"']+)["'][^>]+name=["']generator["']""", re.I)
_VERSIONED = re.compile(r"^([A-Za-z][A-Za-z .+\-]*?)[/ ]+v?(\d+(?:\.\d+){0,3})\b")
_SERVER_SOFTWARE = {
    "nginx": "nginx",
    "apache": "Apache",
    "microsoft-iis": "Microsoft IIS",
    "litespeed": "LiteSpeed",
}


def _split_version(value: str) -> tuple[str, str]:
    match = _VERSIONED.match(value.strip())
    return (match.group(1).strip(), match.group(2)) if match else (value.strip(), "")


def detect_technologies(html: str, headers: dict[str, str]) -> list[TechFinding]:
    """Findings from the page source and (lowercased) response headers, deduplicated by name."""
    found: dict[str, TechFinding] = {}

    def add(finding: TechFinding) -> None:
        existing = found.get(finding.name)
        if existing is None:
            found[finding.name] = finding
        elif finding.version and not existing.version:
            existing.version = finding.version

    source = (html or "").lower()
    for name, category, needles in _HTML_SIGNATURES:
        hit = next((n for n in needles if n in source), None)
        if hit:
            add(TechFinding(name=name, category=category, evidence=f"page source references '{hit}'"))

    for match in (*_GENERATOR.findall(html or ""), *_GENERATOR_ALT.findall(html or "")):
        name, version = _split_version(match)
        if name:
            add(TechFinding(name=name, category="cms", evidence="generator meta tag", version=version))

    lowered = {k.lower(): v for k, v in headers.items()}
    for name, category, header, needle in _HEADER_SIGNATURES:
        value = lowered.get(header)
        if value is not None and needle in value.lower():
            add(TechFinding(name=name, category=category, evidence=f"'{header}' response header"))

    server = lowered.get("server", "")
    for key, label in _SERVER_SOFTWARE.items():
        if key in server.lower():
            _, version = _split_version(server)
            add(
                TechFinding(
                    name=label, category="server", evidence="'server' response header", version=version
                )
            )
            break

    powered = lowered.get("x-powered-by", "")
    if powered:
        name, version = _split_version(powered)
        add(
            TechFinding(
                name=name, category="server", evidence="'x-powered-by' response header", version=version
            )
        )

    return list(found.values())[:MAX_FINDINGS]
