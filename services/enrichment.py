"""Contact enrichment engine — BYOK provider abstraction + waterfall logic.

Users connect their own API keys. Auggie orchestrates the calls.
"""

import logging
from abc import ABC, abstractmethod

import httpx

from database import get_integration

logger = logging.getLogger(__name__)


# =============================================================================
# Provider abstraction
# =============================================================================

class EnrichmentProvider(ABC):
    """Base class for contact enrichment providers."""

    name: str  # e.g. "apollo", "leadmagic"
    cost_per_contact: float  # credits cost (0 = free)

    @abstractmethod
    async def enrich(self, domain: str, api_key: str, *, company_name: str = "") -> list[dict]:
        """Return contacts for a company domain.

        Each contact dict should have:
            first_name, last_name, title, email, email_status, profile_url, company_name
        """
        ...


class ApolloEnrichmentProvider(EnrichmentProvider):
    """Enrich contacts via Apollo people search — free if user has Apollo connected."""

    name = "apollo"
    cost_per_contact = 0.0

    async def enrich(self, domain: str, api_key: str, *, company_name: str = "") -> list[dict]:
        clean_domain = domain.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
        contacts = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Search for people at this domain
            resp = await client.post(
                "https://api.apollo.io/v1/mixed_people/search",
                headers={"Content-Type": "application/json", "X-Api-Key": api_key},
                json={
                    "q_organization_domains": clean_domain,
                    "page": 1,
                    "per_page": 25,
                },
            )
            if resp.status_code >= 400:
                logger.warning("Apollo people search failed for %s: %s %s", clean_domain, resp.status_code, resp.text[:200])
                return []

            people = resp.json().get("people", [])
            logger.info("Apollo enrichment found %d people for %s", len(people), clean_domain)

            for person in people:
                email = person.get("email")
                if not email:
                    continue
                contacts.append({
                    "first_name": person.get("first_name", ""),
                    "last_name": person.get("last_name", ""),
                    "title": person.get("title", ""),
                    "email": email,
                    "email_status": person.get("email_status", ""),
                    "profile_url": person.get("linkedin_url", ""),
                    "company_name": person.get("organization", {}).get("name", "") or company_name,
                    "name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                })

        return contacts


# =============================================================================
# Provider registry
# =============================================================================

PROVIDERS: dict[str, EnrichmentProvider] = {
    "apollo": ApolloEnrichmentProvider(),
}


# =============================================================================
# Waterfall engine
# =============================================================================

async def get_provider_priority(user_id: int) -> list[str]:
    """Return the user's enrichment providers in priority order.

    Currently: check which providers the user has connected, return in
    default priority order. Later this can be user-configurable.
    """
    priority_order = ["apollo"]  # expand as providers are added
    connected = []
    for provider_name in priority_order:
        integration = await get_integration(user_id, provider_name)
        if integration:
            connected.append(provider_name)
    return connected


async def enrich_company_contacts(
    user_id: int,
    domain: str,
    company_name: str = "",
) -> list[dict]:
    """Waterfall enrichment: try providers in priority order until one returns contacts.

    Returns list of contact dicts ready for save_enriched_contacts().
    """
    providers = await get_provider_priority(user_id)
    if not providers:
        logger.warning("No enrichment providers connected for user %d", user_id)
        return []

    for provider_name in providers:
        provider = PROVIDERS.get(provider_name)
        if not provider:
            continue

        integration = await get_integration(user_id, provider_name)
        if not integration:
            continue

        api_key = integration["access_token"]
        try:
            contacts = await provider.enrich(domain, api_key, company_name=company_name)
            if contacts:
                logger.info("Enrichment via %s returned %d contacts for %s", provider_name, len(contacts), domain)
                return contacts
            logger.info("Enrichment via %s returned 0 contacts for %s, trying next", provider_name, domain)
        except Exception as e:
            logger.warning("Enrichment via %s failed for %s: %s", provider_name, domain, e)
            continue

    logger.info("No enrichment provider returned contacts for %s", domain)
    return []
