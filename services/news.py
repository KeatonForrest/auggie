"""news.py - SerpAPI integration for fetching recent company news via Google News."""

import httpx
from typing import Optional

from config import get_settings


class NewsService:
    """Service for fetching recent news about companies via SerpAPI Google News."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.serp_api_key
        self.base_url = "https://serpapi.com/search"

    async def get_company_news(
        self,
        company_name: str,
        max_articles: int = 5,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[str]:
        """
        Fetch recent news articles about a company using SerpAPI Google News.

        Returns formatted string for Claude, or None if no API key or no results.
        """
        if not self.api_key:
            return None

        search_query = self._clean_company_name(company_name)

        try:
            if client is None:
                async with httpx.AsyncClient() as client:
                    return await self._fetch_news(client, search_query, max_articles)
            else:
                return await self._fetch_news(client, search_query, max_articles)
        except Exception as e:
            print(f"SerpAPI error: {e}")
            return None

    async def _fetch_news(self, client: httpx.AsyncClient, search_query: str, max_articles: int) -> Optional[str]:
        """Internal: fetch news with a provided client."""
        response = await client.get(
            self.base_url,
            params={
                "engine": "google_news",
                "q": search_query,
                "api_key": self.api_key,
            },
            timeout=15.0,
        )

        if response.status_code != 200:
            print(f"SerpAPI error: {response.status_code} - {response.text}")
            return None

        data = response.json()
        articles = data.get("news_results", [])[:max_articles]

        if not articles:
            return None

        return self._format_articles(articles)

    def _clean_company_name(self, name: str) -> str:
        """Remove common suffixes for better search results."""
        suffixes = [
            ", Inc.", ", Inc", " Inc.", " Inc",
            ", Corp.", ", Corp", " Corp.", " Corp",
            ", LLC", " LLC",
            ", Ltd.", ", Ltd", " Ltd.", " Ltd",
            ".com", ".io", ".ai",
        ]
        cleaned = name
        for suffix in suffixes:
            if cleaned.endswith(suffix):
                cleaned = cleaned[:-len(suffix)]
        return cleaned.strip()

    def _format_articles(self, articles: list) -> str:
        """Format SerpAPI news results into a string for Claude."""
        lines = []
        for article in articles:
            title = article.get("title", "")
            source = article.get("source", {}).get("name", "Unknown")
            date = article.get("date", "")
            snippet = article.get("snippet", "")
            link = article.get("link", "")

            if title:
                lines.append(f"**{title}**")
                lines.append(f"Source: {source} | {date}")
                if snippet:
                    lines.append(f"{snippet}")
                if link:
                    lines.append(f"Link: {link}")
                lines.append("")

        return "\n".join(lines) if lines else None
