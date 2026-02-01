"""DNS-based infrastructure analysis."""

import asyncio
import logging
from typing import Optional

import aiodns

from models import DNSProfile

logger = logging.getLogger(__name__)

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


class DNSAnalyzer:
    """Analyze DNS records to infer infrastructure providers."""

    async def analyze(self, domain: str) -> DNSProfile:
        profile = DNSProfile(domain=domain)
        resolver = aiodns.DNSResolver()

        try:
            ns_task = self._query(resolver, domain, "NS")
            mx_task = self._query(resolver, domain, "MX")
            txt_task = self._query(resolver, domain, "TXT")
            dmarc_task = self._query(resolver, f"_dmarc.{domain}", "TXT")

            ns_records, mx_records, txt_records, dmarc_records = await asyncio.gather(
                ns_task, mx_task, txt_task, dmarc_task
            )

            # NS -> provider
            if ns_records:
                profile.ns_provider = self._infer_ns_provider(ns_records)
                cloud_hint = profile.ns_provider
                if cloud_hint and cloud_hint in ("AWS", "Cloudflare", "GCP", "Azure"):
                    profile.cloud_provider_hints.append(cloud_hint)

            # MX -> email provider
            if mx_records:
                profile.mx_provider = self._infer_mx_provider(mx_records)

            # TXT -> SPF, DKIM hints
            if txt_records:
                for rec in txt_records:
                    text = self._txt_text(rec)
                    if text.startswith("v=spf1"):
                        profile.has_spf = True
                        profile.txt_signals.append("SPF")
                    if "dkim" in text.lower():
                        profile.has_dkim = True
                        profile.txt_signals.append("DKIM")

            # DMARC
            if dmarc_records:
                for rec in dmarc_records:
                    text = self._txt_text(rec)
                    if text.startswith("v=DMARC1"):
                        profile.has_dmarc = True
                        profile.txt_signals.append("DMARC")
                        # Parse policy
                        for part in text.split(";"):
                            part = part.strip()
                            if part.startswith("p="):
                                profile.dmarc_policy = part[2:].strip()

        except Exception as e:
            logger.warning("DNS analysis failed for %s: %s", domain, e)

        return profile

    async def _query(self, resolver: aiodns.DNSResolver, name: str, qtype: str) -> list:
        try:
            return await resolver.query(name, qtype)
        except (aiodns.error.DNSError, Exception):
            return []

    def _infer_ns_provider(self, ns_records: list) -> Optional[str]:
        for rec in ns_records:
            host = str(getattr(rec, "host", rec)).lower()
            for key, provider in NS_PROVIDER_MAP.items():
                if key in host:
                    return provider
        return None

    def _infer_mx_provider(self, mx_records: list) -> Optional[str]:
        for rec in mx_records:
            host = str(getattr(rec, "host", rec)).lower()
            for key, provider in MX_PROVIDER_MAP.items():
                if key in host:
                    return provider
        return None

    @staticmethod
    def _txt_text(rec) -> str:
        if hasattr(rec, "text"):
            return rec.text
        return str(rec)
