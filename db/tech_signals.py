"""Persist and query normalized tech signals and pain inferences."""

import json
import logging
from typing import Optional

from db._pool import get_connection
from models import TechStack, DNSProfile, SSLProfile, JobSignals, PainInference

logger = logging.getLogger(__name__)


async def save_tech_signals(
    document_id: int,
    tech_by_domain: dict[str, TechStack],
    dns_profile: Optional[DNSProfile] = None,
    ssl_profile: Optional[SSLProfile] = None,
    job_signals: Optional[JobSignals] = None,
) -> int:
    """Flatten all signals into tech_signals rows. Returns count inserted."""
    rows = []

    # Tech detections
    for domain, stack in tech_by_domain.items():
        if isinstance(stack, TechStack):
            for t in stack.technologies:
                rows.append((
                    document_id, domain, "wappalyzer", t.name,
                    t.category, t.confidence or 100, t.version, "{}",
                ))

    # DNS signals
    if dns_profile:
        domain = dns_profile.domain
        if dns_profile.ns_provider:
            rows.append((document_id, domain, "dns", dns_profile.ns_provider, "dns-ns", 100, None, "{}"))
        if dns_profile.mx_provider:
            rows.append((document_id, domain, "dns", dns_profile.mx_provider, "dns-mx", 100, None, "{}"))
        for hint in dns_profile.cloud_provider_hints:
            rows.append((document_id, domain, "dns", hint, "cloud-hint", 80, None, "{}"))

    # SSL signals
    if ssl_profile and ssl_profile.issuer:
        rows.append((
            document_id, ssl_profile.domain, "ssl", ssl_profile.issuer, "ssl-issuer", 100, None,
            json.dumps({"expiry_days": ssl_profile.expiry_days, "automation": ssl_profile.automation_inferred}),
        ))

    # Job signals
    if job_signals:
        for tm in job_signals.tech_mentions:
            rows.append((document_id, "", "job_posting", tm.name, tm.category, 80, None, json.dumps({"count": tm.count})))

    if not rows:
        return 0

    async with get_connection() as conn:
        await conn.executemany(
            """INSERT INTO tech_signals (document_id, domain, signal_source, tech_name, tech_category, confidence, version, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)""",
            rows,
        )
    return len(rows)


async def save_pain_inferences(document_id: int, inferences: list[PainInference]) -> int:
    """Insert pain inference rows. Returns count inserted."""
    if not inferences:
        return 0

    rows = [
        (document_id, i.rule_id, i.title, i.description, i.severity, i.confidence, json.dumps(i.evidence))
        for i in inferences
    ]

    async with get_connection() as conn:
        await conn.executemany(
            """INSERT INTO pain_inferences (document_id, rule_id, title, description, severity, confidence, evidence)
               VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)""",
            rows,
        )
    return len(rows)


RULE_CATEGORIES: dict[str, str] = {
    "identity_fragmentation": "marketing",
    "tech_debt": "engineering",
    "security_gap": "security",
    "scaling_pressure": "engineering",
    "multi_cloud": "operations",
    "email_risk": "security",
    "cert_gap": "security",
    "marketing_product_mismatch": "marketing",
    "data_infra_pain": "data",
    "tag_bloat": "marketing",
    "vendor_lock_in": "operations",
    "compliance_gap": "security",
    "frontend_performance_debt": "engineering",
    "hiring_velocity_anomaly": "operations",
    "tool_sprawl": "operations",
    "observability_gap": "operations",
    "database_scaling_pressure": "engineering",
    "auth_fragmentation": "security",
}


async def get_pain_inferences(document_id: int) -> list[dict]:
    """Retrieve pain inferences for a document, ordered by confidence DESC."""
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT rule_id, title, description, severity, confidence, evidence
               FROM pain_inferences
               WHERE document_id = $1
               ORDER BY confidence DESC""",
            document_id,
        )
        results = []
        for r in rows:
            d = dict(r)
            d["category"] = RULE_CATEGORIES.get(d["rule_id"], "engineering")
            # evidence is stored as JSONB
            if isinstance(d["evidence"], str):
                d["evidence"] = json.loads(d["evidence"])
            results.append(d)
        return results


async def get_signals_for_domain(domain: str, limit: int = 500) -> list[dict]:
    """Query tech signals for a domain with join to research_documents."""
    async with get_connection() as conn:
        rows = await conn.fetch(
            """SELECT ts.*, rd.company_url, rd.company_name
               FROM tech_signals ts
               JOIN research_documents rd ON rd.id = ts.document_id
               WHERE ts.domain = $1
               ORDER BY ts.created_at DESC
               LIMIT $2""",
            domain, limit,
        )
        return [dict(r) for r in rows]
