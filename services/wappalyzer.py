"""wappalyzer.py - Technology detection service using python-Wappalyzer."""

import asyncio
import httpx
from typing import Optional
from urllib.parse import urlparse

from models import TechStack, DetectedTechnology

try:
    from Wappalyzer import Wappalyzer, WebPage
    WAPPALYZER_AVAILABLE = True
except ImportError:
    WAPPALYZER_AVAILABLE = False


class WappalyzerService:
    """Service for detecting technologies on websites."""

    COMMON_APP_SUBDOMAINS = [
        "app", "dashboard", "portal", "console", "platform",
        "admin", "my", "account", "api", "web",
    ]

    def __init__(self):
        if not WAPPALYZER_AVAILABLE:
            print("Warning: python-Wappalyzer not installed. Tech detection disabled.")
            self.wappalyzer = None
        else:
            self.wappalyzer = Wappalyzer.latest()

    def _parse_technologies(self, results: dict, url: str) -> TechStack:
        """Parse wappalyzer results into TechStack model."""
        technologies = []

        for tech_name, tech_info in results.items():
            versions = tech_info.get("versions", [])
            version = versions[0] if versions else None
            categories = tech_info.get("categories", [])
            category = ", ".join(categories) if categories else None

            technologies.append(DetectedTechnology(
                name=tech_name,
                version=version,
                category=category,
                confidence=100
            ))

        technologies.sort(key=lambda t: (t.category or "zzz", t.name))
        return TechStack(technologies=technologies, scan_url=url)

    async def analyze_url(self, url: str) -> TechStack:
        """Analyze a URL to detect technologies."""
        if not self.wappalyzer:
            return TechStack(technologies=[], scan_url=url)

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._sync_analyze_url, url)
        except Exception as e:
            print(f"Error analyzing {url}: {e}")
            return TechStack(technologies=[], scan_url=url)

    def _sync_analyze_url(self, url: str) -> TechStack:
        """Synchronous URL analysis (runs in thread pool)."""
        try:
            webpage = WebPage.new_from_url(url)
            results = self.wappalyzer.analyze_with_versions_and_categories(webpage)
            return self._parse_technologies(results, url)
        except Exception as e:
            print(f"Wappalyzer error for {url}: {e}")
            return TechStack(technologies=[], scan_url=url)

    async def analyze_html(
        self,
        html: str,
        url: str,
        headers: Optional[dict] = None
    ) -> TechStack:
        """Analyze HTML content to detect technologies (efficient when HTML already available)."""
        if not self.wappalyzer:
            return TechStack(technologies=[], scan_url=url)

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self._sync_analyze_html, html, url, headers or {}
            )
        except Exception as e:
            print(f"Error analyzing HTML from {url}: {e}")
            return TechStack(technologies=[], scan_url=url)

    def _sync_analyze_html(self, html: str, url: str, headers: dict) -> TechStack:
        """Synchronous HTML analysis (runs in thread pool)."""
        try:
            webpage = WebPage(url, html, headers)
            results = self.wappalyzer.analyze_with_versions_and_categories(webpage)
            return self._parse_technologies(results, url)
        except Exception as e:
            print(f"Wappalyzer HTML error for {url}: {e}")
            return TechStack(technologies=[], scan_url=url)

    async def _check_subdomain_exists(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        """Check if a subdomain exists via HEAD request."""
        try:
            response = await client.head(url, follow_redirects=True, timeout=5.0)
            if response.status_code < 400:
                return url
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout):
            pass
        except Exception:
            pass
        return None

    async def discover_subdomains(self, base_domain: str) -> list[str]:
        """Discover which app subdomains exist for a domain."""
        base_domain = base_domain.replace("https://", "").replace("http://", "")
        base_domain = base_domain.split("/")[0].replace("www.", "")

        urls_to_check = [f"https://{sub}.{base_domain}" for sub in self.COMMON_APP_SUBDOMAINS]

        print(f"Checking {len(urls_to_check)} potential app subdomains...")

        async with httpx.AsyncClient() as client:
            tasks = [self._check_subdomain_exists(client, url) for url in urls_to_check]
            results = await asyncio.gather(*tasks)

        found = [url for url in results if url is not None]

        if found:
            print(f"Found {len(found)} app subdomains: {found}")
        else:
            print("No app subdomains found")

        return found

    async def analyze_multiple_domains(
        self,
        main_url: str,
        main_html: Optional[str] = None,
    ) -> dict[str, TechStack]:
        """Analyze main domain plus discovered app subdomains."""
        results = {}

        parsed = urlparse(main_url if main_url.startswith("http") else f"https://{main_url}")
        base_domain = parsed.netloc.replace("www.", "")

        print(f"Analyzing main domain: {base_domain}")
        if main_html:
            main_tech = await self.analyze_html(main_html, main_url)
        else:
            main_tech = await self.analyze_url(main_url)

        if main_tech.technologies:
            results[base_domain] = main_tech

        subdomains = await self.discover_subdomains(base_domain)

        if subdomains:
            print(f"Analyzing {len(subdomains)} subdomains...")
            tasks = [self.analyze_url(url) for url in subdomains]
            subdomain_results = await asyncio.gather(*tasks, return_exceptions=True)

            for url, tech in zip(subdomains, subdomain_results):
                if isinstance(tech, Exception):
                    print(f"Error analyzing {url}: {tech}")
                    continue
                if tech.technologies:
                    subdomain_name = urlparse(url).netloc
                    results[subdomain_name] = tech

        return results
