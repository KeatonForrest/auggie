"""Collapsed infrastructure analysis: DNS + SSL + security headers + robots.txt.

One function, one output. Replaces separate DNSAnalyzer, SSLAnalyzer, and the
security header / robots.txt methods that lived on TechDetectionService.
"""

import asyncio
import logging
import ssl
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import aiodns

from models import InfrastructureSignals
from services.collect import get_shared_http_client

logger = logging.getLogger(__name__)

# ── DNS provider maps ──

NS_PROVIDER_MAP = {
    "awsdns": "AWS",
    "cloudflare": "Cloudflare",
    "google": "GCP",
    "azure-dns": "Azure",
    "digitalocean": "DigitalOcean",
    "ns-cloud": "GCP",
}

MX_PROVIDER_MAP = {
    "google": "Google Workspace",
    "googlemail": "Google Workspace",
    "outlook": "Microsoft 365",
    "microsoft": "Microsoft 365",
    "protonmail": "ProtonMail",
    "mimecast": "Mimecast",
}

# ── Security headers to check ──

_SECURITY_HEADERS = [
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
]


async def analyze(domain: str, response_headers: dict | None = None, robots_base_url: str | None = None) -> InfrastructureSignals:
    """Run all infrastructure analysis in parallel and return a single result.

    Args:
        domain: Bare domain (no scheme), e.g. "example.com"
        response_headers: HTTP response headers from the main page (for security header scoring)
        robots_base_url: Full base URL for robots.txt fetch, e.g. "https://example.com"
    """
    dns_task = _analyze_dns(domain)
    ssl_task = _analyze_ssl(domain)
    async def _noop_robots():
        return (None, None)
    robots_task = _fetch_robots(robots_base_url) if robots_base_url else _noop_robots()

    dns_result, ssl_result, robots_result = await asyncio.gather(
        dns_task, ssl_task, robots_task, return_exceptions=True,
    )

    signals = InfrastructureSignals(domain=domain)

    # DNS
    if isinstance(dns_result, dict):
        signals.ns_provider = dns_result.get("ns_provider")
        signals.mx_provider = dns_result.get("mx_provider")
        signals.has_spf = dns_result.get("has_spf", False)
        signals.has_dkim = dns_result.get("has_dkim", False)
        signals.has_dmarc = dns_result.get("has_dmarc", False)
        signals.dmarc_policy = dns_result.get("dmarc_policy")
        signals.cloud_provider_hints = dns_result.get("cloud_provider_hints", [])
    elif isinstance(dns_result, Exception):
        logger.warning("DNS analysis failed for %s: %s", domain, dns_result)

    # SSL
    if isinstance(ssl_result, dict):
        signals.ssl_issuer = ssl_result.get("issuer")
        signals.ssl_expiry_days = ssl_result.get("expiry_days")
        signals.ssl_san_count = ssl_result.get("san_count", 0)
        signals.ssl_is_wildcard = ssl_result.get("is_wildcard", False)
        signals.ssl_automation_inferred = ssl_result.get("automation_inferred", False)
    elif isinstance(ssl_result, Exception):
        logger.warning("SSL analysis failed for %s: %s", domain, ssl_result)

    # Security headers
    if response_headers:
        _score_security_headers(signals, response_headers)

    # Robots.txt
    if isinstance(robots_result, tuple):
        robots_text, _ = robots_result
        if robots_text:
            _extract_robots_signals(signals, robots_text)
    elif isinstance(robots_result, Exception):
        logger.warning("Robots.txt fetch failed for %s: %s", domain, robots_result)

    return signals


# ── DNS ──

async def _analyze_dns(domain: str) -> dict:
    resolver = aiodns.DNSResolver()
    result: dict = {
        "ns_provider": None, "mx_provider": None,
        "has_spf": False, "has_dkim": False, "has_dmarc": False,
        "dmarc_policy": None, "cloud_provider_hints": [],
    }

    ns, mx, txt, dmarc = await asyncio.gather(
        _dns_query(resolver, domain, "NS"),
        _dns_query(resolver, domain, "MX"),
        _dns_query(resolver, domain, "TXT"),
        _dns_query(resolver, f"_dmarc.{domain}", "TXT"),
    )

    if ns:
        for rec in ns:
            host = str(getattr(rec, "host", rec)).lower()
            for key, provider in NS_PROVIDER_MAP.items():
                if key in host:
                    result["ns_provider"] = provider
                    if provider in ("AWS", "Cloudflare", "GCP", "Azure"):
                        result["cloud_provider_hints"].append(provider)
                    break
            if result["ns_provider"]:
                break

    if mx:
        for rec in mx:
            host = str(getattr(rec, "host", rec)).lower()
            for key, provider in MX_PROVIDER_MAP.items():
                if key in host:
                    result["mx_provider"] = provider
                    break
            if result["mx_provider"]:
                break

    if txt:
        for rec in txt:
            text = _txt_text(rec)
            if text.startswith("v=spf1"):
                result["has_spf"] = True
            if "dkim" in text.lower():
                result["has_dkim"] = True

    if dmarc:
        for rec in dmarc:
            text = _txt_text(rec)
            if text.startswith("v=DMARC1"):
                result["has_dmarc"] = True
                for part in text.split(";"):
                    part = part.strip()
                    if part.startswith("p="):
                        result["dmarc_policy"] = part[2:].strip()

    return result


async def _dns_query(resolver: aiodns.DNSResolver, name: str, qtype: str) -> list:
    try:
        return await resolver.query(name, qtype)
    except (aiodns.error.DNSError, Exception):
        return []


def _txt_text(rec) -> str:
    if hasattr(rec, "text"):
        return rec.text
    return str(rec)


# ── SSL ──

async def _analyze_ssl(domain: str) -> dict:
    result: dict = {
        "issuer": None, "expiry_days": None, "san_count": 0,
        "is_wildcard": False, "automation_inferred": False,
    }
    ctx = ssl.create_default_context()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(domain, 443, ssl=ctx), timeout=5.0,
        )
        ssl_obj = writer.get_extra_info("ssl_object")
        if ssl_obj:
            cert = ssl_obj.getpeercert()
            if cert:
                _parse_cert(cert, result)
        writer.close()
        await writer.wait_closed()
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError, ssl.SSLError) as e:
        logger.warning("SSL analysis failed for %s: %s", domain, e)
    except Exception as e:
        logger.warning("SSL analysis unexpected error for %s: %s", domain, e)
    return result


def _parse_cert(cert: dict, result: dict) -> None:
    issuer = cert.get("issuer", ())
    for rdn in issuer:
        for attr_type, attr_value in rdn:
            if attr_type == "organizationName":
                result["issuer"] = attr_value

    not_after = cert.get("notAfter")
    if not_after:
        try:
            expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
            result["expiry_days"] = (expiry.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
        except (ValueError, TypeError):
            pass

    sans = cert.get("subjectAltName", ())
    result["san_count"] = len(sans)
    for san_type, san_value in sans:
        if san_value.startswith("*."):
            result["is_wildcard"] = True
            break

    if result["issuer"] and "let's encrypt" in result["issuer"].lower():
        result["automation_inferred"] = True


# ── Security headers ──

def _score_security_headers(signals: InfrastructureSignals, headers: dict) -> None:
    lower_headers = {k.lower(): v for k, v in headers.items()}
    present = [h for h in _SECURITY_HEADERS if h in lower_headers]
    missing = [h for h in _SECURITY_HEADERS if h not in lower_headers]
    score = len(present)
    if score == 6:
        grade = "A"
    elif score >= 4:
        grade = "B"
    elif score == 3:
        grade = "C"
    elif score >= 1:
        grade = "D"
    else:
        grade = "F"
    signals.security_score = score
    signals.security_present = present
    signals.security_missing = missing
    signals.security_grade = grade


# ── Robots.txt ──

async def _fetch_robots(base_url: str) -> tuple[Optional[str], None]:
    """Fetch robots.txt and return (text, None) or (None, None)."""
    if not base_url:
        return None, None
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{origin}/robots.txt"
    try:
        client = await get_shared_http_client()
        ua = {"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"}
        resp = await client.get(robots_url, follow_redirects=True, timeout=5.0, headers=ua)
        if resp.status_code < 400:
            return resp.text, None
    except Exception:
        pass
    return None, None


def _extract_robots_signals(signals: InfrastructureSignals, robots_text: str) -> None:
    for line in robots_text.splitlines():
        line = line.strip()
        lower = line.lower()
        if lower.startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if not path:
                continue
            if "/api" in path.lower() or "/graphql" in path.lower():
                signals.robots_api_paths.append(path)
            if "/admin" in path.lower():
                signals.robots_admin_paths.append(path)
            signals.robots_interesting_disallows.append(path)
        elif lower.startswith("crawl-delay:"):
            try:
                signals.robots_crawl_delay = float(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                pass
