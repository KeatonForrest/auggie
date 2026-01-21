"""firecrawl.py - Web scraping service using Firecrawl API."""

import httpx
import asyncio
from typing import Optional
from urllib.parse import urljoin, urlparse

from models import ScrapedContent
from config import get_settings


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
                print(f"Firecrawl error for {url}: {response.status_code}")
                return (None, None) if include_html else None

        except httpx.TimeoutException:
            print(f"Timeout scraping {url}")
            return (None, None) if include_html else None
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return (None, None) if include_html else None

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
                print(f"Firecrawl crawl error: {response.status_code}")
                return []

            data = response.json()
            crawl_id = data.get("id")
            if not crawl_id:
                print("No crawl ID returned")
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
                    print(f"Crawl failed: {status_data}")
                    return []

            print("Crawl timed out")
            return []

        except Exception as e:
            print(f"Error crawling site: {e}")
            return []

    async def _scrape_job_board(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        domain: str
    ) -> Optional[str]:
        """Scrape job postings from common job boards (Greenhouse, Lever)."""
        job_board_urls = [
            f"https://boards.greenhouse.io/{company_name.lower().replace(' ', '')}",
            f"https://boards.greenhouse.io/{domain.split('.')[0]}",
            f"https://jobs.lever.co/{company_name.lower().replace(' ', '')}",
            f"https://jobs.lever.co/{domain.split('.')[0]}",
            f"https://{domain}/careers",
            f"https://{domain}/jobs",
            f"https://careers.{domain}",
            f"https://jobs.{domain}",
        ]

        job_content = []
        for url in job_board_urls:
            try:
                content = await self._scrape_url(client, url)
                if content and len(content) > 500:
                    job_content.append(f"## Jobs from {url}\n\n{content}")
                    if "greenhouse.io" in url or "lever.co" in url:
                        break
            except Exception as e:
                print(f"Error scraping job board {url}: {e}")
                continue

        return "\n\n---\n\n".join(job_content) if job_content else None

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
                print(f"Firecrawl search error: {response.status_code}")
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
            print(f"Error in web search: {e}")
            return None

    async def scrape_company(self, company_url: str) -> ScrapedContent:
        """Comprehensive scraping of a company's web presence."""
        if not company_url.startswith(("http://", "https://")):
            company_url = f"https://{company_url}"

        parsed = urlparse(company_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        domain = parsed.netloc.replace("www.", "")
        company_name = domain.split(".")[0]

        print(f"Starting comprehensive scrape for {domain}...")

        async with httpx.AsyncClient() as client:
            print("Running all scraping tasks in parallel...")

            other_urls = {
                "about": urljoin(base_url, "/about"),
                "careers": urljoin(base_url, "/careers"),
                "blog": urljoin(base_url, "/blog"),
                "products": urljoin(base_url, "/products"),
                "solutions": urljoin(base_url, "/solutions"),
                "platform": urljoin(base_url, "/platform"),
                "engineering": urljoin(base_url, "/engineering"),
            }

            # Homepage needs HTML for Wappalyzer tech detection
            homepage_task = self._scrape_url(client, base_url, include_html=True)
            other_tasks = {name: self._scrape_url(client, url) for name, url in other_urls.items()}
            job_task = self._scrape_job_board(client, company_name, domain)
            search_task = self._parallel_search(client, company_name)

            results = await asyncio.gather(
                homepage_task,
                *other_tasks.values(),
                job_task,
                search_task,
                return_exceptions=True
            )

            # Unpack results
            homepage_result = results[0]
            if isinstance(homepage_result, Exception):
                homepage_markdown, homepage_html = None, None
            else:
                homepage_markdown, homepage_html = homepage_result

            core_results = {}
            for i, name in enumerate(other_tasks.keys()):
                result = results[i + 1]
                if not isinstance(result, Exception):
                    core_results[name] = result

            job_postings = results[-2] if not isinstance(results[-2], Exception) else None
            news_content = results[-1] if not isinstance(results[-1], Exception) else None

            extra_pages = []
            for key in ["products", "solutions", "platform", "engineering"]:
                content = core_results.get(key)
                if content and len(content) > 200:
                    extra_pages.append(content)

            additional_content = "\n\n---\n\n".join(extra_pages) if extra_pages else None

        print("Scraping complete!")

        return ScrapedContent(
            homepage=homepage_markdown,
            homepage_html=homepage_html,
            about=core_results.get("about"),
            careers=core_results.get("careers"),
            blog=core_results.get("blog"),
            job_postings=job_postings,
            additional_pages=additional_content,
            news=news_content,
        )

    async def _parallel_search(self, client: httpx.AsyncClient, company_name: str) -> Optional[str]:
        """Run multiple searches in parallel and combine results."""
        search_queries = [
            f"{company_name} engineering blog",
            f"{company_name} tech stack technology",
        ]

        tasks = [self._web_search(client, query, num_results=3) for query in search_queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        news_parts = [r for r in results if isinstance(r, str) and r]
        return "\n\n---\n\n".join(news_parts) if news_parts else None
