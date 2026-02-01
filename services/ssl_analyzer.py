"""SSL/TLS certificate analysis."""

import asyncio
import logging
import ssl
from datetime import datetime, timezone
from typing import Optional

from models import SSLProfile

logger = logging.getLogger(__name__)


class SSLAnalyzer:
    """Analyze SSL certificates to infer automation and infrastructure."""

    async def analyze(self, domain: str) -> SSLProfile:
        profile = SSLProfile(domain=domain)
        ctx = ssl.create_default_context()

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(domain, 443, ssl=ctx),
                timeout=5.0,
            )
            ssl_obj = writer.get_extra_info("ssl_object")
            if ssl_obj:
                cert = ssl_obj.getpeercert()
                if cert:
                    self._parse_cert(cert, profile)
            writer.close()
            await writer.wait_closed()
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError, ssl.SSLError) as e:
            logger.warning("SSL analysis failed for %s: %s", domain, e)
        except Exception as e:
            logger.warning("SSL analysis unexpected error for %s: %s", domain, e)

        return profile

    def _parse_cert(self, cert: dict, profile: SSLProfile) -> None:
        # Issuer
        issuer = cert.get("issuer", ())
        for rdn in issuer:
            for attr_type, attr_value in rdn:
                if attr_type == "organizationName":
                    profile.issuer = attr_value

        # Expiry
        not_after = cert.get("notAfter")
        if not_after:
            try:
                expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                profile.expiry_days = (expiry - datetime.now(timezone.utc).replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        # SANs
        sans = cert.get("subjectAltName", ())
        profile.san_count = len(sans)
        for san_type, san_value in sans:
            if san_value.startswith("*."):
                profile.is_wildcard = True
                break

        # Automation inference
        if profile.issuer and "let's encrypt" in profile.issuer.lower():
            profile.automation_inferred = True
