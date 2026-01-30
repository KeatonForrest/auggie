"""reviews.py - G2 and Capterra review scraping for competitive intelligence."""

import httpx
from typing import Optional

from config import get_settings


class ReviewsService:
    """Service for scraping G2 and Capterra reviews via Firecrawl."""

    def __init__(self):
        self.settings = get_settings()
        self.firecrawl_url = "https://api.firecrawl.dev/v1"
        self.headers = {
            "Authorization": f"Bearer {self.settings.firecrawl_api_key}",
            "Content-Type": "application/json",
        }

    async def get_reviews(self, company_name: str, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
        """
        Fetch G2 and Capterra review data for a company.

        Returns formatted string for Claude prompt, or None if nothing found.
        """
        try:
            if client is None:
                async with httpx.AsyncClient() as client:
                    return await self._get_reviews_impl(client, company_name)
            else:
                return await self._get_reviews_impl(client, company_name)
        except Exception as e:
            print(f"Reviews scraping error (non-fatal): {e}")
            return None

    async def _get_reviews_impl(self, client: httpx.AsyncClient, company_name: str) -> Optional[str]:
        """Internal implementation with a provided client."""
        import asyncio
        g2_task = self._scrape_g2(client, company_name)
        capterra_task = self._scrape_capterra(client, company_name)
        g2_result, capterra_result = await asyncio.gather(
            g2_task, capterra_task, return_exceptions=True
        )

        sections = []

        if isinstance(g2_result, str) and g2_result:
            sections.append("### G2 Reviews")
            sections.append(g2_result)
            sections.append("")

        if isinstance(capterra_result, str) and capterra_result:
            sections.append("### Capterra Reviews")
            sections.append(capterra_result)
            sections.append("")

        if not sections:
            return None

        return "\n".join(sections)

    async def _scrape_g2(self, client: httpx.AsyncClient, company_name: str) -> Optional[str]:
        """Try direct G2 product URL first, fall back to Firecrawl search."""
        clean_name = self._clean_name(company_name)
        slug = clean_name.lower().replace(" ", "-").replace(".", "-")

        # Try direct scrape first (avoids expensive search API call)
        direct_url = f"https://www.g2.com/products/{slug}/reviews"
        try:
            response = await client.post(
                f"{self.firecrawl_url}/scrape",
                headers=self.headers,
                json={"url": direct_url, "formats": ["markdown"]},
                timeout=20.0,
            )
            if response.status_code == 200:
                data = response.json().get("data", {})
                markdown = data.get("markdown", "")
                if markdown and len(markdown) > 200:
                    print(f"G2 direct hit: {direct_url}")
                    return self._extract_g2_content(markdown, direct_url)
        except Exception as e:
            print(f"G2 direct scrape failed (will try search): {e}")

        # Fall back to search
        try:
            response = await client.post(
                f"{self.firecrawl_url}/search",
                headers=self.headers,
                json={
                    "query": f"site:g2.com {clean_name} reviews",
                    "limit": 3,
                    "scrapeOptions": {"formats": ["markdown"]},
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                print(f"G2 search failed: {response.status_code}")
                return None

            data = response.json()
            results = data.get("data", [])

            for result in results:
                url = result.get("url", "")
                markdown = result.get("markdown", "")
                if "g2.com/products/" in url and markdown:
                    return self._extract_g2_content(markdown, url)

            for result in results:
                markdown = result.get("markdown", "")
                url = result.get("url", "")
                if markdown and "g2.com" in url:
                    return self._extract_g2_content(markdown, url)

            return None

        except Exception as e:
            print(f"G2 scrape error: {e}")
            return None

    async def _scrape_capterra(self, client: httpx.AsyncClient, company_name: str) -> Optional[str]:
        """Try direct Capterra URL first, fall back to Firecrawl search."""
        clean_name = self._clean_name(company_name)
        slug = clean_name.lower().replace(" ", "-").replace(".", "-")

        # Try direct scrape first
        direct_url = f"https://www.capterra.com/p/{slug}/reviews/"
        try:
            response = await client.post(
                f"{self.firecrawl_url}/scrape",
                headers=self.headers,
                json={"url": direct_url, "formats": ["markdown"]},
                timeout=20.0,
            )
            if response.status_code == 200:
                data = response.json().get("data", {})
                markdown = data.get("markdown", "")
                if markdown and len(markdown) > 200:
                    print(f"Capterra direct hit: {direct_url}")
                    return self._extract_capterra_content(markdown, direct_url)
        except Exception as e:
            print(f"Capterra direct scrape failed (will try search): {e}")

        # Fall back to search
        try:
            response = await client.post(
                f"{self.firecrawl_url}/search",
                headers=self.headers,
                json={
                    "query": f"site:capterra.com {clean_name} reviews",
                    "limit": 3,
                    "scrapeOptions": {"formats": ["markdown"]},
                },
                timeout=30.0,
            )

            if response.status_code != 200:
                print(f"Capterra search failed: {response.status_code}")
                return None

            data = response.json()
            results = data.get("data", [])

            for result in results:
                url = result.get("url", "")
                markdown = result.get("markdown", "")
                if "capterra.com" in url and markdown:
                    return self._extract_capterra_content(markdown, url)

            return None

        except Exception as e:
            print(f"Capterra scrape error: {e}")
            return None

    def _extract_g2_content(self, markdown: str, url: str) -> str:
        """Extract useful signals from G2 page markdown."""
        lines = []
        lines.append(f"Source: {url}")

        # Truncate to reasonable size — G2 pages can be very long
        content = markdown[:6000]

        # The raw markdown from G2 contains ratings, review counts,
        # pros/cons, and competitor comparisons — all useful for Claude
        lines.append(content)

        return "\n".join(lines)

    def _extract_capterra_content(self, markdown: str, url: str) -> str:
        """Extract useful signals from Capterra page markdown."""
        lines = []
        lines.append(f"Source: {url}")
        content = markdown[:4000]
        lines.append(content)
        return "\n".join(lines)

    def _clean_name(self, name: str) -> str:
        """Clean company name for search queries."""
        for suffix in [".com", ".io", ".ai", ".co", ".org", ".net", ".dev", ".so", ".app"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        for suffix in ["hq", "app", "inc", "corp"]:
            if name.endswith(suffix) and len(name) > len(suffix) + 2:
                name = name[:-len(suffix)]
                break
        return name.strip()
