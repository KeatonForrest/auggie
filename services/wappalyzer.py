"""wappalyzer.py - Technology detection service using python-Wappalyzer."""

import asyncio
import httpx
from typing import Optional
from urllib.parse import urlparse

from models import TechStack, DetectedTechnology
from services.collect import get_shared_http_client

try:
    from Wappalyzer import Wappalyzer, WebPage
    WAPPALYZER_AVAILABLE = True
    print("Wappalyzer module imported successfully")
except ImportError as e:
    WAPPALYZER_AVAILABLE = False
    print(f"Wappalyzer import failed: {e}")


class WappalyzerService:
    """Service for detecting technologies on websites."""

    # B2B SaaS subdomains
    B2B_SUBDOMAINS = [
        "app", "dashboard", "portal", "console", "platform",
        "admin", "my", "account", "api", "web", "cloud",
        "login", "sso", "auth", "id", "secure",
    ]

    # B2C / Retail subdomains
    B2C_SUBDOMAINS = [
        "shop", "store", "checkout", "cart", "orders",
        "member", "members", "rewards", "m", "mobile",
        "www2", "secure", "pay", "payments",
    ]

    # Combined list
    COMMON_APP_SUBDOMAINS = list(set(B2B_SUBDOMAINS + B2C_SUBDOMAINS))

    # Common authenticated paths to check on main domain
    COMMON_APP_PATHS = [
        "/app", "/dashboard", "/portal", "/login", "/signin", "/sign-in",
        "/account", "/member", "/membership", "/my-account", "/profile",
    ]

    def __init__(self):
        if not WAPPALYZER_AVAILABLE:
            print("WARNING: python-Wappalyzer not installed. Tech detection disabled.")
            self.wappalyzer = None
        else:
            try:
                self.wappalyzer = Wappalyzer.latest()
                print("Wappalyzer initialized successfully")
            except Exception as e:
                import traceback
                print(f"ERROR: Failed to initialize Wappalyzer: {e}")
                print(f"Traceback: {traceback.format_exc()}")
                self.wappalyzer = None

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
            print(f"Wappalyzer: Fetching {url}...")
            webpage = WebPage.new_from_url(url)
            print(f"Wappalyzer: Analyzing {url}...")
            results = self.wappalyzer.analyze_with_versions_and_categories(webpage)
            tech_count = len(results) if results else 0
            print(f"Wappalyzer: Found {tech_count} technologies on {url}")
            return self._parse_technologies(results, url)
        except Exception as e:
            print(f"Wappalyzer ERROR for {url}: {e}")
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

    async def _check_url_exists(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        """Check if a URL exists via GET request (more reliable than HEAD)."""
        try:
            # Use GET with limited content - some sites block HEAD requests
            response = await client.get(
                url,
                follow_redirects=True,
                timeout=8.0,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"}
            )
            # Check for success and that we didn't get redirected to main site
            if response.status_code < 400:
                # Avoid false positives from redirects to homepage
                final_url = str(response.url)
                if not final_url.rstrip('/').endswith(('.com', '.org', '.net', '.io', '.co')):
                    return url
                # If it's a subdomain that stayed on subdomain, it's valid
                if url.split('/')[2] == final_url.split('/')[2]:
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

        client = await get_shared_http_client()
        tasks = [self._check_url_exists(client, url) for url in urls_to_check]
        results = await asyncio.gather(*tasks)

        found = [url for url in results if url is not None]

        if found:
            print(f"Found {len(found)} app subdomains: {found}")
        else:
            print("No app subdomains found")

        return found

    async def discover_app_paths(self, base_url: str) -> list[str]:
        """Discover which app paths exist on the main domain."""
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        urls_to_check = [f"{base_url}{path}" for path in self.COMMON_APP_PATHS]

        print(f"Checking {len(urls_to_check)} potential app paths...")

        client = await get_shared_http_client()
        tasks = [self._check_url_exists(client, url) for url in urls_to_check]
        results = await asyncio.gather(*tasks)

        found = [url for url in results if url is not None]

        if found:
            print(f"Found {len(found)} app paths: {found}")

        return found

    async def analyze_multiple_domains(
        self,
        main_url: str,
        main_html: Optional[str] = None,
    ) -> dict[str, TechStack]:
        """Analyze main domain plus discovered app subdomains and paths."""
        results = {}

        if not self.wappalyzer:
            print("Wappalyzer: SKIPPING - wappalyzer not initialized")
            return results

        parsed = urlparse(main_url if main_url.startswith("http") else f"https://{main_url}")
        base_domain = parsed.netloc.replace("www.", "")
        full_main_url = f"https://{base_domain}"

        print(f"Wappalyzer: Analyzing main domain: {full_main_url}")
        if main_html:
            main_tech = await self.analyze_html(main_html, full_main_url)
        else:
            main_tech = await self.analyze_url(full_main_url)
        print(f"Wappalyzer: Main domain result - {len(main_tech.technologies)} technologies")

        # Always include main domain in results (even if empty)
        results[base_domain] = main_tech

        # Discover and analyze subdomains and paths in parallel
        subdomains, app_paths = await asyncio.gather(
            self.discover_subdomains(base_domain),
            self.discover_app_paths(full_main_url)
        )

        # Analyze discovered subdomains
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

        # Analyze discovered app paths (can reveal different tech than homepage)
        if app_paths:
            print(f"Analyzing {len(app_paths)} app paths...")
            tasks = [self.analyze_url(url) for url in app_paths]
            path_results = await asyncio.gather(*tasks, return_exceptions=True)

            for url, tech in zip(app_paths, path_results):
                if isinstance(tech, Exception):
                    print(f"Error analyzing {url}: {tech}")
                    continue
                if tech.technologies:
                    # Use path as key, e.g., "rei.com/account"
                    parsed_url = urlparse(url)
                    path_key = f"{parsed_url.netloc}{parsed_url.path}"
                    # Only add if it has different/additional tech than main domain
                    main_tech_names = {t.name for t in results.get(base_domain, TechStack(technologies=[])).technologies}
                    new_tech = [t for t in tech.technologies if t.name not in main_tech_names]
                    if new_tech:
                        results[path_key] = TechStack(technologies=new_tech, scan_url=url)

        return results
