"""apollo.py - Apollo.io: contact enrichment + integration (API key, saved list import)."""

import logging

import httpx
from typing import Optional
from config import get_settings
from database import get_integration

logger = logging.getLogger(__name__)


class ApolloContact:
    """A contact from Apollo.io."""
    def __init__(
        self,
        name: str,
        title: str,
        email: Optional[str] = None,
        linkedin_url: Optional[str] = None,
        phone: Optional[str] = None,
        seniority: Optional[str] = None,
        department: Optional[str] = None,
    ):
        self.name = name
        self.title = title
        self.email = email
        self.linkedin_url = linkedin_url
        self.phone = phone
        self.seniority = seniority
        self.department = department

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "email": self.email,
            "linkedin_url": self.linkedin_url,
            "phone": self.phone,
            "seniority": self.seniority,
            "department": self.department,
        }


class ApolloService:
    """Service for enriching company contacts using Apollo.io API."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = "https://api.apollo.io/v1"
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.settings.apollo_api_key,
        }

    async def _search_organization(
        self,
        client: httpx.AsyncClient,
        domain: str,
    ) -> Optional[dict]:
        """Search for an organization by domain using Apollo's company search."""
        try:
            # Use mixed_companies/search with q_organization_domains
            response = await client.post(
                f"{self.base_url}/mixed_companies/search",
                headers=self.headers,
                json={
                    "q_organization_domains": domain,
                    "page": 1,
                    "per_page": 1,
                },
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                orgs = data.get("organizations", []) or data.get("accounts", [])
                if orgs:
                    return orgs[0]
            else:
                logger.error("Apollo company search error: %s - %s", response.status_code, response.text[:200])
            return None

        except Exception as e:
            logger.error("Error searching Apollo organization: %s", e)
            return None

    async def _search_contacts(
        self,
        client: httpx.AsyncClient,
        domain: str,
        target_personas: Optional[str] = None,
        limit: int = 10,
    ) -> list[ApolloContact]:
        """Search for contacts at a company by domain using Apollo's people search."""
        try:
            # Build person titles filter from target personas
            person_titles = []
            if target_personas:
                # Parse comma-separated personas into title keywords
                personas = [p.strip().lower() for p in target_personas.split(",")]
                for persona in personas:
                    # Add common title variations
                    if "engineer" in persona or "engineering" in persona:
                        person_titles.extend(["Engineering Manager", "VP Engineering", "CTO", "Head of Engineering", "Director of Engineering"])
                    if "product" in persona:
                        person_titles.extend(["Product Manager", "VP Product", "Head of Product", "CPO", "Director of Product"])
                    if "data" in persona:
                        person_titles.extend(["Data Engineer", "Head of Data", "VP Data", "Chief Data Officer"])
                    if "devops" in persona or "infrastructure" in persona or "platform" in persona:
                        person_titles.extend(["DevOps", "Platform Engineer", "Infrastructure", "SRE"])
                    if "security" in persona:
                        person_titles.extend(["Security", "CISO", "Head of Security"])
                    if "it" in persona or "operations" in persona:
                        person_titles.extend(["IT Manager", "VP IT", "CIO", "IT Director"])
                    if "cto" in persona or "technical" in persona:
                        person_titles.extend(["CTO", "VP Engineering", "Technical"])
                    if "ceo" in persona or "founder" in persona or "executive" in persona:
                        person_titles.extend(["CEO", "Founder", "Co-Founder", "President"])

            # Build the search request for mixed_people/api_search
            search_params = {
                "q_organization_domains": domain,
                "page": 1,
                "per_page": limit,
            }

            # Add title filter if we have target personas
            if person_titles:
                search_params["person_titles"] = list(set(person_titles))  # Dedupe

            response = await client.post(
                f"{self.base_url}/mixed_people/api_search",
                headers=self.headers,
                json=search_params,
                timeout=30.0
            )

            if response.status_code != 200:
                logger.error("Apollo people search error: %s - %s", response.status_code, response.text[:200])
                return []

            data = response.json()
            contacts_data = data.get("people", [])

            contacts = []
            for c in contacts_data:
                # Handle name - API may return obfuscated last name
                first_name = c.get("first_name", "")
                last_name = c.get("last_name") or c.get("last_name_obfuscated", "")
                name = f"{first_name} {last_name}".strip() or c.get("name", "Unknown")

                # Handle email/LinkedIn - may need credits to reveal
                email = c.get("email")
                if not email and c.get("has_email"):
                    email = "(available with credits)"

                linkedin = c.get("linkedin_url")
                if not linkedin and c.get("linkedin_url"):
                    linkedin = c.get("linkedin_url")

                # Get organization name for context
                org = c.get("organization", {})
                org_name = org.get("name", "")

                contact = ApolloContact(
                    name=name,
                    title=c.get("title", ""),
                    email=email,
                    linkedin_url=linkedin,
                    phone=None,  # Usually requires credits
                    seniority=c.get("seniority"),
                    department=c.get("departments", [""])[0] if c.get("departments") else c.get("department"),
                )
                contacts.append(contact)

            return contacts

        except Exception as e:
            logger.error("Error searching Apollo contacts: %s", e)
            return []

    async def get_company_contacts(
        self,
        domain: str,
        target_personas: Optional[str] = None,
        limit: int = 10,
    ) -> tuple[Optional[dict], list[ApolloContact]]:
        """
        Get company info and contacts from Apollo.

        Returns:
            tuple of (organization_info, list of contacts)
        """
        if not self.settings.apollo_api_key:
            logger.warning("Apollo API key not configured")
            return None, []

        # Clean domain
        domain = domain.replace("https://", "").replace("http://", "")
        domain = domain.split("/")[0].replace("www.", "")

        async with httpx.AsyncClient() as client:
            # Get org info and contacts in parallel
            import asyncio
            org_task = self._search_organization(client, domain)
            contacts_task = self._search_contacts(client, domain, target_personas, limit)

            org_info, contacts = await asyncio.gather(org_task, contacts_task)

            if org_info:
                logger.debug("Found Apollo org: %s", org_info.get('name', domain))
            logger.debug("Found %s contacts from Apollo", len(contacts))

            return org_info, contacts

    def format_contacts_for_prompt(
        self,
        org_info: Optional[dict],
        contacts: list[ApolloContact],
    ) -> str:
        """Format Apollo data for inclusion in Claude's prompt."""
        sections = []

        if org_info:
            sections.append("## Company Information (from Apollo.io)")
            sections.append(f"**Company:** {org_info.get('name', 'Unknown')}")
            if org_info.get('short_description'):
                sections.append(f"**Description:** {org_info.get('short_description')}")
            if org_info.get('industry'):
                sections.append(f"**Industry:** {org_info.get('industry')}")
            if org_info.get('estimated_num_employees'):
                sections.append(f"**Employees:** {org_info.get('estimated_num_employees')}")
            if org_info.get('annual_revenue_printed'):
                sections.append(f"**Revenue:** {org_info.get('annual_revenue_printed')}")
            if org_info.get('founded_year'):
                sections.append(f"**Founded:** {org_info.get('founded_year')}")
            if org_info.get('linkedin_url'):
                sections.append(f"**LinkedIn:** {org_info.get('linkedin_url')}")
            sections.append("")

        if contacts:
            sections.append("## Key Contacts (from Apollo.io)")
            sections.append("These contacts match the target personas for your product:")
            sections.append("")

            for i, contact in enumerate(contacts, 1):
                sections.append(f"### {i}. {contact.name}")
                sections.append(f"- **Title:** {contact.title}")
                if contact.seniority:
                    sections.append(f"- **Seniority:** {contact.seniority}")
                if contact.department:
                    sections.append(f"- **Department:** {contact.department}")
                if contact.email:
                    sections.append(f"- **Email:** {contact.email}")
                if contact.linkedin_url:
                    sections.append(f"- **LinkedIn:** {contact.linkedin_url}")
                if contact.phone:
                    sections.append(f"- **Phone:** {contact.phone}")
                sections.append("")

        if not org_info and not contacts:
            return ""

        return "\n".join(sections)

    async def get_firmographics(self, domain: str) -> Optional[str]:
        """
        Get firmographic data for scoring (headcount, revenue, funding, industry).

        Returns formatted string for Claude prompt, or None if no API key or no data.
        """
        if not self.settings.apollo_api_key:
            return None

        domain = domain.replace("https://", "").replace("http://", "")
        domain = domain.split("/")[0].replace("www.", "")

        async with httpx.AsyncClient() as client:
            org = await self._search_organization(client, domain)
            if not org:
                return None

            lines = []
            lines.append(f"**Company:** {org.get('name', domain)}")

            if org.get("industry"):
                lines.append(f"**Industry:** {org['industry']}")
            if org.get("estimated_num_employees"):
                lines.append(f"**Employees:** {org['estimated_num_employees']}")
            if org.get("annual_revenue_printed"):
                lines.append(f"**Revenue:** {org['annual_revenue_printed']}")
            if org.get("annual_revenue"):
                lines.append(f"**Revenue (raw):** ${org['annual_revenue']:,.0f}")
            if org.get("founded_year"):
                lines.append(f"**Founded:** {org['founded_year']}")
            if org.get("total_funding"):
                lines.append(f"**Total Funding:** ${org['total_funding']:,.0f}")
            if org.get("total_funding_printed"):
                lines.append(f"**Total Funding:** {org['total_funding_printed']}")
            if org.get("latest_funding_round_date"):
                lines.append(f"**Latest Funding Round:** {org['latest_funding_round_date']}")
            if org.get("latest_funding_stage"):
                lines.append(f"**Latest Funding Stage:** {org['latest_funding_stage']}")
            if org.get("latest_funding_round_amount"):
                lines.append(f"**Latest Round Amount:** ${org['latest_funding_round_amount']:,.0f}")
            if org.get("publicly_traded_symbol"):
                lines.append(f"**Ticker:** {org['publicly_traded_symbol']}")
                lines.append(f"**Publicly Traded:** Yes")
            if org.get("keywords"):
                keywords = org["keywords"][:10] if isinstance(org["keywords"], list) else []
                if keywords:
                    lines.append(f"**Keywords:** {', '.join(keywords)}")

            # Only return if we got meaningful data beyond just the name
            if len(lines) <= 1:
                return None

            lines.append("")
            lines.append("(This is CONFIRMED firmographic data — use it to validate or override inferred company size/industry for Fit scoring. With confirmed firmographics, the Fit score cap of 65 can be removed.)")

            return "\n".join(lines)


# =============================================================================
# Integration functions (API key connect, saved list import)
# =============================================================================

APOLLO_API_BASE = "https://api.apollo.io/v1"


async def validate_integration_api_key(api_key: str) -> bool:
    """Validate an Apollo API key by making a test call."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{APOLLO_API_BASE}/auth/health",
            headers={"Content-Type": "application/json"},
            json={"api_key": api_key},
        )
        return resp.status_code == 200


async def _get_integration_api_key(user_id: int) -> str:
    """Get a user's Apollo integration API key from integrations table."""
    integration = await get_integration(user_id, "apollo")
    if not integration:
        raise RuntimeError("Apollo not connected")
    return integration["access_token"]


async def list_saved_lists(user_id: int) -> list[dict]:
    """List saved organization lists from Apollo."""
    api_key = await _get_integration_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{APOLLO_API_BASE}/labels",
            headers={"Content-Type": "application/json"},
            json={"api_key": api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("labels", [])


async def fetch_list_companies(user_id: int, list_id: str, page: int = 1) -> dict:
    """Fetch companies from a saved Apollo list.

    Returns {"organizations": [...], "pagination": {...}}.
    """
    api_key = await _get_integration_api_key(user_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{APOLLO_API_BASE}/mixed_companies/search",
            headers={"Content-Type": "application/json"},
            json={
                "api_key": api_key,
                "label_ids": [list_id],
                "page": page,
                "per_page": 100,
            },
        )
        resp.raise_for_status()
        return resp.json()
