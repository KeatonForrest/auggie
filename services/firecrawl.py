"""firecrawl.py - Web scraping service using Firecrawl API."""

import httpx
import asyncio
from typing import Optional
from urllib.parse import urljoin, urlparse

from models import ScrapedContent
from config import get_settings
from services.collect import get_shared_http_client


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
        """Scrape job postings from common job boards and ATS platforms."""
        company_slug = company_name.lower().replace(' ', '').replace('-', '').replace('_', '')
        domain_slug = domain.split('.')[0].lower()

        # Top 3 most common job board URLs (reduced for cost optimization)
        job_board_urls = [
            # Greenhouse
            f"https://boards.greenhouse.io/{company_slug}",
            # Lever
            f"https://jobs.lever.co/{company_slug}",
            # Ashby (popular with tech companies)
            f"https://jobs.ashbyhq.com/{company_slug}",
        ]

        print(f"Checking {len(job_board_urls)} job board URLs...")

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
                    print(f"Found job content at {url}")
                    # Limit to 3 sources to avoid token bloat
                    if len(job_content) >= 3:
                        break

        if job_content:
            return "\n\n---\n\n".join(job_content)

        # Fallback: web search for jobs if direct scraping failed
        print(f"No direct job boards found, searching web for {company_name} jobs...")
        search_result = await self._web_search(
            client,
            f"{company_name} careers jobs hiring",
            num_results=3
        )
        return search_result

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

        client = get_shared_http_client()
        print("Running all scraping tasks in parallel...")

        other_urls = {
            "about": urljoin(base_url, "/about"),
            "careers": urljoin(base_url, "/careers"),
            "blog": urljoin(base_url, "/blog"),
            "engineering": urljoin(base_url, "/engineering"),
        }

        # Homepage needs HTML for Wappalyzer tech detection
        homepage_task = self._scrape_url(client, base_url, include_html=True)
        other_tasks = {name: self._scrape_url(client, url) for name, url in other_urls.items()}
        job_task = self._scrape_job_board(client, company_name, domain)
        investor_task = self._scrape_investor_relations(client, domain)
        engineering_task = self._scrape_engineering_blog(client, domain)
        docs_task = self._scrape_developer_docs(client, domain)

        results = await asyncio.gather(
            homepage_task,
            *other_tasks.values(),
            job_task,
            investor_task,
            engineering_task,
            docs_task,
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

        job_postings = results[-4] if not isinstance(results[-4], Exception) else None
        investor_content = results[-3] if not isinstance(results[-3], Exception) else None
        engineering_subdomain = results[-2] if not isinstance(results[-2], Exception) else None
        docs_content = results[-1] if not isinstance(results[-1], Exception) else None

        # Combine engineering content from /engineering path, subdomains, and docs
        engineering_path = core_results.get("engineering")
        additional_parts = []
        if engineering_path and len(engineering_path) > 200:
            additional_parts.append(engineering_path)
        if engineering_subdomain and len(engineering_subdomain) > 200:
            additional_parts.append(engineering_subdomain)
        if docs_content and len(docs_content) > 200:
            additional_parts.append(docs_content)
        additional_content = "\n\n---\n\n".join(additional_parts) if additional_parts else None

        print("Scraping complete!")

        return ScrapedContent(
            homepage=homepage_markdown,
            homepage_html=homepage_html,
            about=core_results.get("about"),
            careers=core_results.get("careers"),
            blog=core_results.get("blog"),
            job_postings=job_postings,
            additional_pages=additional_content,
            news=None,  # Populated by NewsService in main.py
            investor_relations=investor_content,
        )

    async def _check_subdomain_exists(
        self,
        client: httpx.AsyncClient,
        url: str
    ) -> bool:
        """Check if a subdomain exists with a quick HEAD/GET request."""
        try:
            response = await client.head(
                url,
                follow_redirects=True,
                timeout=5.0,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"}
            )
            # Check if we got a successful response and didn't redirect to main domain
            if response.status_code < 400:
                final_url = str(response.url)
                # Make sure we didn't get redirected to the main site
                if url.split('/')[2] in final_url:
                    return True
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout):
            pass
        except Exception:
            pass
        return False

    async def _scrape_engineering_blog(
        self,
        client: httpx.AsyncClient,
        domain: str
    ) -> Optional[str]:
        """Check for and scrape engineering blog subdomains."""
        # Common engineering blog subdomains
        eng_subdomains = [
            f"https://engineering.{domain}",
            f"https://tech.{domain}",
            f"https://developers.{domain}",
        ]

        # Check which subdomains exist
        check_tasks = [self._check_subdomain_exists(client, url) for url in eng_subdomains]
        exists_results = await asyncio.gather(*check_tasks)

        existing_eng_urls = [url for url, exists in zip(eng_subdomains, exists_results) if exists]

        if not existing_eng_urls:
            return None

        print(f"Found engineering blog subdomain: {existing_eng_urls[0]}")

        # Scrape the first existing engineering subdomain
        eng_url = existing_eng_urls[0]
        content = await self._scrape_url(client, eng_url)

        if content and len(content) > 300:
            return content

        return None

    async def _scrape_developer_docs(
        self,
        client: httpx.AsyncClient,
        domain: str
    ) -> Optional[str]:
        """Check for and scrape developer documentation subdomains."""
        # Common docs/developer subdomains
        doc_subdomains = [
            f"https://docs.{domain}",
            f"https://developer.{domain}",
            f"https://api.{domain}",
        ]

        # Check which subdomains exist (free HEAD requests)
        check_tasks = [self._check_subdomain_exists(client, url) for url in doc_subdomains]
        exists_results = await asyncio.gather(*check_tasks)

        existing_doc_urls = [url for url, exists in zip(doc_subdomains, exists_results) if exists]

        if not existing_doc_urls:
            return None

        print(f"Found developer docs subdomain: {existing_doc_urls[0]}")

        # Scrape the first existing docs subdomain
        doc_url = existing_doc_urls[0]
        content = await self._scrape_url(client, doc_url)

        if content and len(content) > 300:
            return f"## Developer Documentation ({doc_url})\n\n{content}"

        return None

    async def _scrape_investor_relations(
        self,
        client: httpx.AsyncClient,
        domain: str
    ) -> Optional[str]:
        """Check for and scrape investor relations subdomains (public companies only)."""
        # Common investor relations subdomains
        ir_subdomains = [
            f"https://investor.{domain}",
            f"https://investors.{domain}",
            f"https://ir.{domain}",
        ]

        # Check which subdomains exist
        check_tasks = [self._check_subdomain_exists(client, url) for url in ir_subdomains]
        exists_results = await asyncio.gather(*check_tasks)

        existing_ir_urls = [url for url, exists in zip(ir_subdomains, exists_results) if exists]

        if not existing_ir_urls:
            print(f"No investor relations subdomain found for {domain}")
            return None

        print(f"Found investor relations subdomain: {existing_ir_urls[0]}")

        # Scrape the first existing IR subdomain
        ir_url = existing_ir_urls[0]

        # Try to get key pages from the IR site (reduced for cost optimization)
        ir_pages = [
            ir_url,  # Main IR page
            f"{ir_url}/news",
        ]

        scrape_tasks = [self._scrape_url(client, url) for url in ir_pages]
        results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

        content_parts = []
        for url, content in zip(ir_pages, results):
            if isinstance(content, str) and content and len(content) > 300:
                # Truncate each page to avoid token bloat
                content_parts.append(f"### {url}\n\n{content[:4000]}")
                print(f"Scraped IR content from {url}")

        if content_parts:
            return "\n\n---\n\n".join(content_parts)

        return None
