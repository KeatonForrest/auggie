"""wappalyzer.py - Technology detection service using python-Wappalyzer."""

import asyncio
import httpx
import requests
from typing import Optional
from urllib.parse import urlparse

from models import TechStack, DetectedTechnology
from services.collect import get_shared_http_client

import logging
logger = logging.getLogger(__name__)

try:
    from services.techdetect import TechDetector, WebPage
    WAPPALYZER_AVAILABLE = True
    logger.debug("TechDetector module imported successfully")
except ImportError as e:
    WAPPALYZER_AVAILABLE = False
    logger.error("TechDetector import failed: %s", e)


class WappalyzerService:
    """Service for detecting technologies on websites."""

    # High-signal subdomains that reveal tech stack (trimmed from 30+ to top 10)
    COMMON_APP_SUBDOMAINS = [
        "app", "api", "dashboard", "portal", "admin",
        "login", "console", "platform", "shop", "store",
    ]

    # Common authenticated paths to check on main domain
    COMMON_APP_PATHS = [
        "/app", "/dashboard", "/portal", "/login", "/signin", "/sign-in",
        "/account", "/member", "/membership", "/my-account", "/profile",
    ]

    def __init__(self):
        if not WAPPALYZER_AVAILABLE:
            logger.warning("python-Wappalyzer not installed. Tech detection disabled.")
            self.wappalyzer = None
        else:
            try:
                self.wappalyzer = TechDetector()
                logger.debug("TechDetector initialized successfully")
            except Exception as e:
                import traceback
                logger.error("Failed to initialize Wappalyzer: %s", e)
                logger.error("Traceback: %s", traceback.format_exc())
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
            logger.error("Error analyzing %s: %s", url, e)
            return TechStack(technologies=[], scan_url=url)

    def _sync_analyze_url(self, url: str) -> TechStack:
        """Synchronous URL analysis (runs in thread pool)."""
        try:
            logger.debug("Wappalyzer: Fetching %s...", url)
            webpage = WebPage.new_from_url(url)
            logger.debug("Wappalyzer: Analyzing %s...", url)
            results = self.wappalyzer.analyze_with_versions_and_categories(webpage)
            tech_count = len(results) if results else 0
            logger.debug("Wappalyzer: Found %s technologies on %s", tech_count, url)
            return self._parse_technologies(results, url)
        except Exception as e:
            logger.error("Wappalyzer error for %s: %s", url, e)
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
            logger.error("Error analyzing HTML from %s: %s", url, e)
            return TechStack(technologies=[], scan_url=url)

    def _sync_analyze_html(self, html: str, url: str, headers: dict) -> TechStack:
        """Synchronous HTML analysis (runs in thread pool)."""
        try:
            if not headers:
                try:
                    resp = requests.head(url, timeout=5, allow_redirects=True)
                    headers = dict(resp.headers)
                except Exception:
                    pass  # proceed with empty headers — no worse than before
            webpage = WebPage(url, html, headers)
            results = self.wappalyzer.analyze_with_versions_and_categories(webpage)
            return self._parse_technologies(results, url)
        except Exception as e:
            logger.error("Wappalyzer HTML error for %s: %s", url, e)
            return TechStack(technologies=[], scan_url=url)

    async def _check_url_exists(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        """Check if a URL exists. HEAD first (cheap), GET fallback for ambiguous responses."""
        _ua = {"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"}
        try:
            response = await client.head(
                url, follow_redirects=True, timeout=5.0, headers=_ua
            )
            if response.status_code == 404 or response.status_code >= 500:
                return None
            if response.status_code == 405:
                # HEAD not allowed — fall through to GET
                pass
            else:
                return self._validate_redirect(url, response)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout):
            return None
        except Exception:
            pass

        # GET fallback
        try:
            response = await client.get(
                url, follow_redirects=True, timeout=6.0, headers=_ua
            )
            if response.status_code not in (404,) and response.status_code < 500:
                return self._validate_redirect(url, response)
        except Exception:
            pass
        return None

    @staticmethod
    def _validate_redirect(original_url: str, response: httpx.Response) -> Optional[str]:
        """Return original_url if the response didn't redirect to a generic homepage."""
        final_url = str(response.url)
        # If it stayed on the same host, it's valid
        if original_url.split('/')[2] == final_url.split('/')[2]:
            return original_url
        # If the final URL doesn't look like a bare domain root, accept it
        if not final_url.rstrip('/').endswith(('.com', '.org', '.net', '.io', '.co')):
            return original_url
        return None

    async def discover_subdomains(self, base_domain: str) -> list[str]:
        """Discover which app subdomains exist for a domain."""
        base_domain = base_domain.replace("https://", "").replace("http://", "")
        base_domain = base_domain.split("/")[0].replace("www.", "")

        urls_to_check = [f"https://{sub}.{base_domain}" for sub in self.COMMON_APP_SUBDOMAINS]

        logger.debug("Checking %s potential app subdomains...", len(urls_to_check))

        client = await get_shared_http_client()
        tasks = [self._check_url_exists(client, url) for url in urls_to_check]
        results = await asyncio.gather(*tasks)

        found = [url for url in results if url is not None]

        if found:
            logger.debug("Found %s app subdomains: %s", len(found), found)
        else:
            logger.debug("No app subdomains found")

        return found

    async def discover_app_paths(self, base_url: str) -> list[str]:
        """Discover which app paths exist on the main domain."""
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        urls_to_check = [f"{base_url}{path}" for path in self.COMMON_APP_PATHS]

        logger.debug("Checking %s potential app paths...", len(urls_to_check))

        client = await get_shared_http_client()
        tasks = [self._check_url_exists(client, url) for url in urls_to_check]
        results = await asyncio.gather(*tasks)

        found = [url for url in results if url is not None]

        if found:
            logger.debug("Found %s app paths: %s", len(found), found)

        return found

    async def analyze_multiple_domains(
        self,
        main_url: str,
        main_html: Optional[str] = None,
    ) -> dict[str, TechStack]:
        """Analyze main domain plus discovered app subdomains and paths."""
        results = {}

        if not self.wappalyzer:
            logger.debug("Wappalyzer: SKIPPING - wappalyzer not initialized")
            return results

        parsed = urlparse(main_url if main_url.startswith("http") else f"https://{main_url}")
        base_domain = parsed.netloc.replace("www.", "")
        full_main_url = f"https://{base_domain}"

        logger.debug("Wappalyzer: Analyzing main domain: %s", full_main_url)
        if main_html:
            main_tech = await self.analyze_html(main_html, full_main_url)
        else:
            main_tech = await self.analyze_url(full_main_url)
        logger.debug("Wappalyzer: Main domain result - %s technologies", len(main_tech.technologies))

        # Always include main domain in results (even if empty)
        results[base_domain] = main_tech

        # Discover and analyze subdomains and paths in parallel
        subdomains, app_paths = await asyncio.gather(
            self.discover_subdomains(base_domain),
            self.discover_app_paths(full_main_url)
        )

        # Analyze discovered subdomains
        if subdomains:
            logger.debug("Analyzing %s subdomains...", len(subdomains))
            tasks = [self.analyze_url(url) for url in subdomains]
            subdomain_results = await asyncio.gather(*tasks, return_exceptions=True)

            for url, tech in zip(subdomains, subdomain_results):
                if isinstance(tech, Exception):
                    logger.error("Error analyzing %s: %s", url, tech)
                    continue
                if tech.technologies:
                    subdomain_name = urlparse(url).netloc
                    results[subdomain_name] = tech

        # Analyze discovered app paths (can reveal different tech than homepage)
        if app_paths:
            logger.debug("Analyzing %s app paths...", len(app_paths))
            tasks = [self.analyze_url(url) for url in app_paths]
            path_results = await asyncio.gather(*tasks, return_exceptions=True)

            for url, tech in zip(app_paths, path_results):
                if isinstance(tech, Exception):
                    logger.error("Error analyzing %s: %s", url, tech)
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
