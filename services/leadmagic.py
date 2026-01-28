"""LeadMagic API client for contact enrichment."""

import httpx
from typing import Optional
from config import get_settings


class LeadMagicService:
    """Find contacts at companies using LeadMagic's role-finder API."""

    BASE_URL = "https://api.leadmagic.io"

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.leadmagic_api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def find_role(self, company_domain: str, job_title: str, company_name: str = "") -> Optional[dict]:
        """Find a person by role at a company.

        Returns dict with name, first_name, last_name, profile_url, company_name
        or None if not found.
        """
        if not self.is_configured():
            return None

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(
                    f"{self.BASE_URL}/role-finder",
                    headers={"X-API-Key": self.api_key},
                    json={
                        "company_domain": company_domain,
                        "company_name": company_name,
                        "job_title": job_title,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("message") == "Role Found" and data.get("name"):
                        return {
                            "name": data.get("name", ""),
                            "first_name": data.get("first_name", ""),
                            "last_name": data.get("last_name", ""),
                            "title": job_title,
                            "profile_url": data.get("profile_url", ""),
                            "company_name": data.get("company_name", ""),
                        }
                return None
            except Exception as e:
                print(f"LeadMagic role-finder error: {e}")
                return None

    async def find_email(self, first_name: str, last_name: str, domain: str) -> Optional[dict]:
        """Find email for a known person at a company.

        Returns dict with email, status, or None if not found.
        """
        if not self.is_configured():
            return None

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(
                    f"{self.BASE_URL}/email-finder",
                    headers={"X-API-Key": self.api_key},
                    json={
                        "first_name": first_name,
                        "last_name": last_name,
                        "domain": domain,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("email") and data.get("status") in ("valid", "valid_catch_all"):
                        return {
                            "email": data["email"],
                            "status": data["status"],
                        }
                return None
            except Exception as e:
                print(f"LeadMagic email-finder error: {e}")
                return None

    async def enrich_contacts(self, company_domain: str, company_name: str, target_titles: list[str]) -> list[dict]:
        """Find contacts for multiple target titles at a company.

        For each title, finds the person via role-finder, then gets their email.
        Returns list of enriched contacts.
        """
        if not self.is_configured():
            return []

        contacts = []
        for title in target_titles:
            person = await self.find_role(company_domain, title, company_name)
            if not person:
                continue

            # Try to get their email
            email_result = await self.find_email(
                person["first_name"],
                person["last_name"],
                company_domain,
            )
            if email_result:
                person["email"] = email_result["email"]
                person["email_status"] = email_result["status"]

            contacts.append(person)

        return contacts
