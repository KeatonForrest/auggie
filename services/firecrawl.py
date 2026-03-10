"""firecrawl.py - Web scraping service using Firecrawl API."""

import logging
import re
import httpx
import asyncio
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urlparse

from models import ScrapedContent
from config import get_settings
from services.collect import get_shared_http_client


logger = logging.getLogger(__name__)


class FirecrawlService:
    """Service for scraping websites using Firecrawl API."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = "https://api.firecrawl.dev/v1"
        self.headers = {
            "Authorization": f"Bearer {self.settings.firecrawl_api_key}",
            "Content-Type": "application/json"
        }

    async def _scrape_url(
        self,
        client: httpx.AsyncClient,
        url: str,
        include_html: bool = False
    ) -> Optional[str] | tuple[Optional[str], Optional[str]]:
        """Scrape a single URL. Returns (markdown, html) tuple if include_html=True."""
        try:
            formats = ["markdown", "html"] if include_html else ["markdown"]
            response = await client.post(
                f"{self.base_url}/scrape",
                headers=self.headers,
                json={"url": url, "formats": formats},
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                markdown = data.get("data", {}).get("markdown")
                if include_html:
                    html = data.get("data", {}).get("html")
                    return (markdown, html)
                return markdown
            else:
                logger.error("Firecrawl error for %s: %s", url, response.status_code)
                return (None, None) if include_html else None

        except httpx.TimeoutException:
            logger.debug("Timeout scraping %s", url)
            return (None, None) if include_html else None
        except Exception as e:
            logger.error("Error scraping %s: %s", url, e)
            return (None, None) if include_html else None

    async def _map_site(
        self,
        client: httpx.AsyncClient,
        url: str,
        max_links: int = 50,
    ) -> list[str]:
        """Discover site URLs via Firecrawl's map endpoint."""
        try:
            response = await client.post(
                "https://api.firecrawl.dev/v2/map",
                headers=self.headers,
                json={"url": url, "limit": max_links},
                timeout=30.0,
            )
            if response.status_code != 200:
                logger.error("Firecrawl map error for %s: %s", url, response.status_code)
                return []

            body = response.json()
            data = body.get("data", [])
            if isinstance(data, dict):
                candidates = data.get("links") or data.get("urls") or []
            else:
                candidates = data

            discovered: list[str] = []
            for item in candidates:
                if isinstance(item, str) and item:
                    discovered.append(item)
                elif isinstance(item, dict):
                    candidate = item.get("url") or item.get("link")
                    if candidate:
                        discovered.append(candidate)
            return discovered
        except Exception as e:
            logger.error("Error mapping %s: %s", url, e)
            return []

    async def _crawl_site(self, client: httpx.AsyncClient, url: str, max_pages: int = 10) -> list[str]:
        """Crawl multiple pages from a site. Returns list of markdown content."""
        try:
            response = await client.post(
                f"{self.base_url}/crawl",
                headers=self.headers,
                json={
                    "url": url,
                    "limit": max_pages,
                    "scrapeOptions": {"formats": ["markdown"]}
                },
                timeout=30.0
            )

            if response.status_code != 200:
                logger.error("Firecrawl crawl error: %s", response.status_code)
                return []

            data = response.json()
            crawl_id = data.get("id")
            if not crawl_id:
                logger.error("No crawl ID returned")
                return []

            # Poll for completion
            for _ in range(30):
                await asyncio.sleep(2)
                status_response = await client.get(
                    f"{self.base_url}/crawl/{crawl_id}",
                    headers=self.headers,
                    timeout=15.0
                )

                if status_response.status_code != 200:
                    continue

                status_data = status_response.json()
                status = status_data.get("status")

                if status == "completed":
                    pages = status_data.get("data", [])
                    return [p.get("markdown", "") for p in pages if p.get("markdown")]
                elif status == "failed":
                    logger.error("Crawl failed: %s", status_data)
                    return []

            logger.error("Crawl timed out")
            return []

        except Exception as e:
            logger.error("Error crawling site: %s", e)
            return []

    async def _scrape_job_board(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        domain: str
    ) -> Optional[str]:
        """Scrape job postings from common job boards and ATS platforms."""
        company_slug = company_name.lower().replace(' ', '').replace('-', '').replace('_', '')

        # Top 3 most common job board URLs (reduced for cost optimization)
        job_board_urls = [
            # Greenhouse
            f"https://boards.greenhouse.io/{company_slug}",
            # Lever
            f"https://jobs.lever.co/{company_slug}",
            # Ashby (popular with tech companies)
            f"https://jobs.ashbyhq.com/{company_slug}",
        ]

        logger.debug("Checking %s job board URLs...", len(job_board_urls))

        # Check all URLs in parallel for speed
        tasks = [self._scrape_url(client, url) for url in job_board_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        job_content = []
        seen_content = set()  # Avoid duplicates

        for url, content in zip(job_board_urls, results):
            if isinstance(content, Exception) or not content:
                continue
            if len(content) > 500:
                # Simple dedup based on first 200 chars
                content_sig = content[:200]
                if content_sig not in seen_content:
                    seen_content.add(content_sig)
                    job_content.append(f"## Jobs from {url}\n\n{content[:8000]}")
                    logger.debug("Found job content at %s", url)
                    # Limit to 3 sources to avoid token bloat
                    if len(job_content) >= 3:
                        break

        if job_content:
            return "\n\n---\n\n".join(job_content)

        logger.debug("No supported direct job boards found for %s", company_name)
        return None

    async def _web_search(
        self,
        client: httpx.AsyncClient,
        query: str,
        num_results: int = 5
    ) -> Optional[str]:
        """Search the web and return scraped content from results."""
        try:
            response = await client.post(
                f"{self.base_url}/search",
                headers=self.headers,
                json={
                    "query": query,
                    "limit": num_results,
                    "scrapeOptions": {"formats": ["markdown"]}
                },
                timeout=45.0
            )

            if response.status_code != 200:
                logger.error("Firecrawl search error: %s", response.status_code)
                return None

            data = response.json()
            results = data.get("data", [])
            if not results:
                return None

            content_parts = []
            for result in results:
                title = result.get("title", "")
                url = result.get("url", "")
                markdown = result.get("markdown", "")
                if markdown:
                    content_parts.append(f"### {title}\nSource: {url}\n\n{markdown[:3000]}")

            return "\n\n---\n\n".join(content_parts) if content_parts else None

        except Exception as e:
            logger.error("Error in web search: %s", e)
            return None

    async def scrape_company(self, company_url: str) -> ScrapedContent:
        """Comprehensive scraping of a company's web presence."""
        if not company_url.startswith(("http://", "https://")):
            company_url = f"https://{company_url}"

        parsed = urlparse(company_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        domain = parsed.netloc.replace("www.", "")
        company_name = domain.split(".")[0]

        logger.debug("Starting comprehensive scrape for %s...", domain)

        client = await get_shared_http_client()
        logger.debug("Running reduced scraping tasks in parallel...")

        # Homepage needs HTML for tech detection
        homepage_task = self._scrape_url(client, base_url, include_html=True)
        job_task = self._scrape_job_board(client, company_name, domain)
        sitemap_task = self._fetch_sitemap(client, base_url)

        homepage_result, job_result, sitemap_result = await asyncio.gather(
            homepage_task,
            job_task,
            sitemap_task,
            return_exceptions=True
        )

        if isinstance(homepage_result, Exception):
            homepage_markdown, homepage_html = None, None
        else:
            homepage_markdown, homepage_html = homepage_result

        job_postings = job_result if not isinstance(job_result, Exception) else None
        sitemap_urls = sitemap_result if not isinstance(sitemap_result, Exception) else {}

        logger.debug("Scraping complete!")

        return ScrapedContent(
            homepage=homepage_markdown,
            homepage_html=homepage_html,
            about=None,
            careers=None,
            blog=None,
            job_postings=job_postings,
            additional_pages=None,
            site_structure=sitemap_urls or None,
            news=None,
            investor_relations=None,
            web_mentions=None,
        )

    # URL path patterns for sitemap categorization
    _SITEMAP_PATTERNS: dict[str, list[re.Pattern]] = {
        "careers": [
            re.compile(r"^/careers/?$", re.I),
            re.compile(r"^/jobs/?$", re.I),
            re.compile(r"^/join-?us/?$", re.I),
            re.compile(r"^/work-?with-?us/?$", re.I),
            re.compile(r"^/openings/?$", re.I),
        ],
        "docs": [
            re.compile(r"^/docs/?$", re.I),
            re.compile(r"^/api/docs/?$", re.I),
            re.compile(r"^/documentation/?$", re.I),
            re.compile(r"^/developers?/?$", re.I),
            re.compile(r"^/developer-?docs/?$", re.I),
        ],
        "status": [
            re.compile(r"^/status/?$", re.I),
            re.compile(r"^/status-page/?$", re.I),
            re.compile(r"^/system-?status/?$", re.I),
        ],
        "platform": [
            re.compile(r"^/platform/?$", re.I),
            re.compile(r"^/workspace/?$", re.I),
            re.compile(r"^/console/?$", re.I),
            re.compile(r"^/app/?$", re.I),
        ],
        "products": [
            re.compile(r"^/products/?$", re.I),
            re.compile(r"^/solutions/?$", re.I),
            re.compile(r"^/services/?$", re.I),
            re.compile(r"^/features/?$", re.I),
        ],
        "security": [
            re.compile(r"^/security/?$", re.I),
            re.compile(r"^/trust/?$", re.I),
        ],
    }

    async def _fetch_sitemap(
        self,
        client: httpx.AsyncClient,
        base_url: str,
    ) -> dict[str, str]:
        """Fetch and parse sitemap.xml for high-value page URLs.

        Returns a dict mapping category (careers, docs, status, platform, etc.) to
        the best URL found for that category. Uses plain HTTP — zero Firecrawl
        credits.
        """
        try:
            response = await client.get(
                f"{base_url}/sitemap.xml",
                timeout=5.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"},
            )
            if response.status_code != 200:
                return {}

            content = response.text
            # Handle sitemap index: grab the first child sitemap URL
            if "<sitemapindex" in content:
                try:
                    root = ET.fromstring(content)
                    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                    first_loc = root.find(".//sm:loc", ns)
                    if first_loc is None or not first_loc.text:
                        return {}
                    child_resp = await client.get(
                        first_loc.text.strip(),
                        timeout=5.0,
                        follow_redirects=True,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"},
                    )
                    if child_resp.status_code != 200:
                        return {}
                    content = child_resp.text
                except Exception:
                    return {}

            root = ET.fromstring(content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            locs = root.findall(".//sm:loc", ns)
            # Fallback: try without namespace (some sitemaps omit it)
            if not locs:
                locs = root.findall(".//{*}loc")
            if not locs:
                locs = root.findall(".//loc")

            discovered: dict[str, str] = {}
            for loc in locs:
                url = (loc.text or "").strip()
                if not url:
                    continue
                path = urlparse(url).path
                for category, patterns in self._SITEMAP_PATTERNS.items():
                    if category in discovered:
                        continue
                    for pat in patterns:
                        if pat.match(path):
                            discovered[category] = url
                            break

            if discovered:
                logger.debug("Sitemap discovered pages: %s", list(discovered.keys()))
            return discovered

        except (httpx.TimeoutException, httpx.ConnectError):
            return {}
        except ET.ParseError:
            logger.debug("Failed to parse sitemap.xml (malformed XML)")
            return {}
        except Exception:
            return {}
