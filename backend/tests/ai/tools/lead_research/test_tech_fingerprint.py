from app.ai.tools.lead_research.tech_fingerprint import MAX_FINDINGS, detect_technologies


def _names(findings):
    return {f.name: f for f in findings}


def test_wordpress_site_is_recognised_with_its_evidence():
    html = '<link rel="stylesheet" href="/wp-content/themes/x/style.css"><script src="/wp-includes/js/jquery.js">'

    found = _names(detect_technologies(html, {}))

    assert found["WordPress"].category == "cms"
    assert "/wp-content/" in found["WordPress"].evidence
    assert "jQuery" in found


def test_generator_meta_tag_gives_a_version_in_either_attribute_order():
    a = detect_technologies('<meta name="generator" content="WordPress 6.4.2">', {})
    b = detect_technologies('<meta content="Drupal 10.1 (https://www.drupal.org)" name="generator">', {})

    assert _names(a)["WordPress"].version == "6.4.2"
    assert _names(b)["Drupal"].version == "10.1"


def test_generator_and_signature_findings_are_merged_not_duplicated():
    html = '<meta name="generator" content="WordPress 6.4.2"><link href="/wp-content/a.css">'

    findings = detect_technologies(html, {})

    wordpress = [f for f in findings if f.name == "WordPress"]
    assert len(wordpress) == 1 and wordpress[0].version == "6.4.2"


def test_modern_frameworks_analytics_and_marketing_tools():
    html = """
    <script src="/_next/static/chunks/main.js"></script>
    <script src="https://www.googletagmanager.com/gtm.js?id=GTM-1"></script>
    <script src="https://js.hs-scripts.com/123.js"></script>
    <script src="https://widget.intercom.io/widget/abc"></script>
    <script src="https://js.stripe.com/v3/"></script>
    """

    found = _names(detect_technologies(html, {}))

    assert {"Next.js", "Google Tag Manager", "HubSpot", "Intercom", "Stripe"} <= set(found)
    assert found["HubSpot"].category == "marketing" and found["Stripe"].category == "payments"


def test_response_headers_reveal_hosting_and_server_software_and_versions():
    headers = {
        "Server": "nginx/1.18.0",
        "X-Powered-By": "PHP/7.4.33",
        "CF-Ray": "abc123",
        "x-vercel-id": "iad1::abc",
    }

    found = _names(detect_technologies("", headers))

    assert found["Cloudflare"].category == "hosting"
    assert found["Vercel"].category == "hosting"
    assert (found["nginx"].category, found["nginx"].version) == ("server", "1.18.0")
    assert (found["PHP"].category, found["PHP"].version) == ("server", "7.4.33")


def test_header_names_are_case_insensitive():
    assert "Cloudflare" in _names(detect_technologies("", {"CF-RAY": "x"}))
    assert "Cloudflare" in _names(detect_technologies("", {"Server": "cloudflare"}))


def test_version_is_only_reported_when_the_site_discloses_it():
    found = _names(detect_technologies("", {"Server": "nginx"}))

    assert found["nginx"].version == ""


def test_a_plain_page_yields_nothing():
    assert detect_technologies("<html><body><h1>Hello</h1></body></html>", {}) == []
    assert detect_technologies("", {}) == []


def test_findings_are_capped():
    html = "".join(f'<meta name="generator" content="Tool{i} 1.0">' for i in range(60))

    assert len(detect_technologies(html, {})) == MAX_FINDINGS
