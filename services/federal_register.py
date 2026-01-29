"""federal_register.py - Federal Register API for upcoming compliance deadlines."""

import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Optional


# Map SIC codes to regulatory search terms
SIC_TO_TOPICS = {
    # Finance
    "60": ["banking regulation", "financial compliance", "anti-money laundering"],
    "61": ["lending regulation", "consumer financial protection", "CFPB"],
    "62": ["securities regulation", "SEC compliance", "investment adviser"],
    "63": ["insurance regulation", "NAIC compliance"],
    "64": ["insurance regulation"],
    "67": ["investment regulation", "SEC compliance"],
    # Healthcare
    "80": ["HIPAA", "healthcare regulation", "CMS compliance"],
    "28": ["FDA regulation", "pharmaceutical compliance", "drug safety"],
    "38": ["medical device regulation", "FDA compliance"],
    # Technology
    "73": ["data privacy", "cybersecurity regulation", "AI regulation"],
    "48": ["telecommunications regulation", "FCC compliance"],
    # Energy
    "13": ["energy regulation", "EPA compliance", "environmental"],
    "49": ["utility regulation", "FERC compliance", "energy"],
    # Manufacturing
    "20": ["food safety", "FDA regulation", "USDA compliance"],
    "35": ["manufacturing safety", "OSHA compliance"],
    "36": ["electronic equipment regulation", "FCC compliance"],
    "37": ["transportation safety", "NHTSA regulation"],
    # Retail/Consumer
    "52": ["consumer protection", "FTC regulation", "product safety"],
    "53": ["consumer protection", "FTC regulation"],
    "54": ["consumer protection", "FTC regulation"],
    # Defense
    "97": ["defense regulation", "DFARS compliance", "CMMC"],
    # Real Estate
    "65": ["real estate regulation", "fair housing", "RESPA"],
    # Transportation
    "40": ["transportation regulation", "DOT compliance"],
    "41": ["transportation regulation", "DOT compliance"],
    "42": ["transportation regulation", "DOT compliance", "FMCSA"],
    "44": ["transportation regulation", "maritime regulation"],
    "45": ["aviation regulation", "FAA compliance"],
}

# Default topics if no SIC match
DEFAULT_TOPICS = ["data privacy", "cybersecurity regulation"]

BASE_URL = "https://www.federalregister.gov/api/v1/documents.json"


class FederalRegisterService:
    """Service for finding upcoming compliance deadlines from the Federal Register."""

    async def get_upcoming_regulations(
        self,
        company_name: str,
        sic_code: Optional[str] = None,
        industry_keywords: Optional[list[str]] = None,
    ) -> Optional[str]:
        """
        Search Federal Register for upcoming regulations relevant to a company.

        Args:
            company_name: Company name (used in output formatting)
            sic_code: SIC code from EDGAR (e.g., "7372")
            industry_keywords: Additional search terms from company description

        Returns formatted string for Claude prompt, or None if nothing relevant found.
        """
        # Build search terms from SIC code
        search_terms = []
        if sic_code:
            prefix = sic_code[:2]
            search_terms = SIC_TO_TOPICS.get(prefix, DEFAULT_TOPICS)
        elif industry_keywords:
            search_terms = industry_keywords
        else:
            search_terms = DEFAULT_TOPICS

        try:
            async with httpx.AsyncClient() as client:
                # Search for recent and upcoming rules across relevant topics
                all_results = []
                tasks = [
                    self._search_regulations(client, term)
                    for term in search_terms[:3]  # Limit to 3 searches to be respectful
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, list):
                        all_results.extend(result)

                if not all_results:
                    return None

                # Deduplicate by title
                seen = set()
                unique = []
                for reg in all_results:
                    if reg["title"] not in seen:
                        seen.add(reg["title"])
                        unique.append(reg)

                # Sort by effective date (soonest first)
                unique.sort(key=lambda r: r.get("effective_on") or "9999-12-31")

                # Take top results
                unique = unique[:8]

                return self._format_results(unique)

        except Exception as e:
            print(f"Federal Register error (non-fatal): {e}")
            return None

    async def _search_regulations(
        self, client: httpx.AsyncClient, term: str
    ) -> list[dict]:
        """Search for recent rules and proposed rules matching a term."""
        # Look for rules with effective dates in the past 6 months or future
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        try:
            response = await client.get(
                BASE_URL,
                params={
                    "conditions[term]": term,
                    "conditions[type][]": ["RULE", "PRORULE"],
                    "conditions[effective_date][gte]": six_months_ago,
                    "fields[]": [
                        "title", "effective_on", "agencies", "abstract",
                        "type", "publication_date", "html_url",
                    ],
                    "per_page": 5,
                    "order": "relevance",
                },
                timeout=15.0,
            )

            if response.status_code != 200:
                return []

            data = response.json()
            return data.get("results", [])

        except Exception:
            return []

    def _format_results(self, regulations: list[dict]) -> str:
        """Format regulations into a string for Claude prompt."""
        lines = []

        for reg in regulations:
            title = reg.get("title", "Unknown")
            effective = reg.get("effective_on", "TBD")
            pub_date = reg.get("publication_date", "")
            reg_type = reg.get("type", "")
            abstract = reg.get("abstract", "")
            agencies = [a.get("name", "") for a in reg.get("agencies", []) if a.get("name")]

            type_label = "Final Rule" if reg_type == "Rule" else "Proposed Rule"
            agency_str = ", ".join(agencies) if agencies else "Unknown agency"

            lines.append(f"**{title}**")
            lines.append(f"Type: {type_label} | Agency: {agency_str}")
            lines.append(f"Published: {pub_date} | Effective: {effective}")
            if abstract:
                # Truncate long abstracts
                short = abstract[:500]
                if len(abstract) > 500:
                    short += "..."
                lines.append(f"Summary: {short}")
            lines.append("")

        return "\n".join(lines) if lines else None
