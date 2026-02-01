"""wappalyzer.py - Technology detection service using python-Wappalyzer."""

import asyncio
import httpx
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from models import TechStack, DetectedTechnology, SecurityPosture, RobotsSignals
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
        self._semaphore = asyncio.Semaphore(3)
        self._robots_cache: dict[str, Optional[RobotFileParser]] = {}
        self._robots_text_cache: dict[str, str] = {}
        self._last_main_headers: dict = {}

    def _parse_technologies(self, results: dict, url: str) -> TechStack:
        """Parse wappalyzer results into TechStack model."""
        technologies = []

        for tech_name, tech_info in results.items():
            versions = tech_info.get("versions", [])
            version = versions[0] if versions else None
            categories = tech_info.get("categories", [])
            category = ", ".join(categories) if categories else None

            confidence = tech_info.get("confidence", 100)

            technologies.append(DetectedTechnology(
                name=tech_name,
                version=version,
                category=category,
                confidence=confidence,
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
            # Fetch headers async if not provided, instead of sync requests.head
            if not headers:
                headers = await self._fetch_headers(url)
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self._sync_analyze_html, html, url, headers
            )
        except Exception as e:
            logger.error("Error analyzing HTML from %s: %s", url, e)
            return TechStack(technologies=[], scan_url=url)

    async def _fetch_headers(self, url: str) -> dict:
        """Fetch response headers for a URL using async httpx HEAD request."""
        try:
            client = await get_shared_http_client()
            _ua = {"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"}
            resp = await client.head(url, follow_redirects=True, timeout=5.0, headers=_ua)
            return dict(resp.headers)
        except Exception:
            return {}

    def _sync_analyze_html(self, html: str, url: str, headers: dict) -> TechStack:
        """Synchronous HTML analysis (runs in thread pool)."""
        try:
            webpage = WebPage(url, html, headers)
            results = self.wappalyzer.analyze_with_versions_and_categories(webpage)
            return self._parse_technologies(results, url)
        except Exception as e:
            logger.error("Wappalyzer HTML error for %s: %s", url, e)
            return TechStack(technologies=[], scan_url=url)

    async def _rate_limited_check(self, client: httpx.AsyncClient, url: str) -> Optional[tuple[str, dict]]:
        """Rate-limited wrapper around _check_url_exists."""
        async with self._semaphore:
            result = await self._check_url_exists(client, url)
            await asyncio.sleep(0.3)
            return result

    async def _check_url_exists(self, client: httpx.AsyncClient, url: str) -> Optional[tuple[str, dict]]:
        """Check if a URL exists. Returns (url, headers) or None.
        HEAD first (cheap), GET fallback only for 405."""
        _ua = {"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"}
        try:
            response = await client.head(
                url, follow_redirects=True, timeout=5.0, headers=_ua
            )
            if response.status_code == 404 or response.status_code >= 400:
                return None
            if response.status_code == 405:
                # HEAD not allowed — fall through to GET
                pass
            else:
                validated = self._validate_redirect(url, response)
                if validated:
                    return (validated, dict(response.headers))
                return None
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout):
            return None
        except Exception:
            pass

        # GET fallback (only reached on 405 or non-network HEAD errors)
        try:
            response = await client.get(
                url, follow_redirects=True, timeout=6.0, headers=_ua
            )
            if response.status_code < 400:
                validated = self._validate_redirect(url, response)
                if validated:
                    return (validated, dict(response.headers))
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

    async def _fetch_robots(self, base_url: str) -> Optional[RobotFileParser]:
        """Fetch and cache robots.txt for a domain."""
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots_cache:
            return self._robots_cache[origin]

        rp = RobotFileParser()
        robots_url = f"{origin}/robots.txt"
        try:
            client = await get_shared_http_client()
            _ua = {"User-Agent": "Mozilla/5.0 (compatible; AuggieBot/1.0)"}
            resp = await client.get(robots_url, follow_redirects=True, timeout=5.0, headers=_ua)
            if resp.status_code < 400:
                rp.parse(resp.text.splitlines())
                self._robots_cache[origin] = rp
                self._robots_text_cache[origin] = resp.text
                return rp
        except Exception:
            pass
        self._robots_cache[origin] = None
        return None

    def get_robots_text(self, base_url: str) -> str | None:
        """Retrieve cached robots.txt text for a base URL."""
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return self._robots_text_cache.get(origin)

    def get_last_main_headers(self) -> dict:
        """Return headers captured from the last main domain analysis."""
        return self._last_main_headers

    @staticmethod
    def score_security_headers(headers: dict) -> SecurityPosture:
        """Score presence of 6 key security headers."""
        check_headers = [
            "strict-transport-security",
            "content-security-policy",
            "x-frame-options",
            "x-content-type-options",
            "referrer-policy",
            "permissions-policy",
        ]
        lower_headers = {k.lower(): v for k, v in headers.items()}
        present = [h for h in check_headers if h in lower_headers]
        missing = [h for h in check_headers if h not in lower_headers]
        score = len(present)
        if score == 6:
            grade = "A"
        elif score >= 4:
            grade = "B"
        elif score == 3:
            grade = "C"
        elif score >= 1:
            grade = "D"
        else:
            grade = "F"
        return SecurityPosture(score=score, present=present, missing=missing, grade=grade)

    @staticmethod
    def extract_robots_signals(robots_text: str) -> RobotsSignals:
        """Extract interesting signals from robots.txt content."""
        api_paths = []
        admin_paths = []
        interesting = []
        crawl_delay = None

        for line in robots_text.splitlines():
            line = line.strip()
            lower = line.lower()
            if lower.startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if not path:
                    continue
                if "/api" in path.lower() or "/graphql" in path.lower():
                    api_paths.append(path)
                if "/admin" in path.lower():
                    admin_paths.append(path)
                interesting.append(path)
            elif lower.startswith("crawl-delay:"):
                try:
                    crawl_delay = float(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass

        return RobotsSignals(
            api_paths=api_paths,
            admin_paths=admin_paths,
            crawl_delay=crawl_delay,
            interesting_disallows=interesting,
        )

    async def discover_subdomains(self, base_domain: str) -> list[tuple[str, dict]]:
        """Discover which app subdomains exist for a domain.
        Returns list of (url, headers) tuples."""
        base_domain = base_domain.replace("https://", "").replace("http://", "")
        base_domain = base_domain.split("/")[0].replace("www.", "")

        urls_to_check = [f"https://{sub}.{base_domain}" for sub in self.COMMON_APP_SUBDOMAINS]

        logger.debug("Checking %s potential app subdomains...", len(urls_to_check))

        client = await get_shared_http_client()
        tasks = [self._rate_limited_check(client, url) for url in urls_to_check]
        results = await asyncio.gather(*tasks)

        found = [r for r in results if r is not None]

        if found:
            logger.debug("Found %s app subdomains: %s", len(found), [u for u, _ in found])
        else:
            logger.debug("No app subdomains found")

        return found

    async def discover_app_paths(self, base_url: str) -> list[tuple[str, dict]]:
        """Discover which app paths exist on the main domain.
        Returns list of (url, headers) tuples. Respects robots.txt."""
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        # Fetch robots.txt and filter disallowed paths
        rp = await self._fetch_robots(base_url)
        paths_to_check = self.COMMON_APP_PATHS
        if rp is not None:
            paths_to_check = [
                p for p in paths_to_check
                if rp.can_fetch("AuggieBot", p)
            ]

        urls_to_check = [f"{base_url}{path}" for path in paths_to_check]

        logger.debug("Checking %s potential app paths...", len(urls_to_check))

        client = await get_shared_http_client()
        tasks = [self._rate_limited_check(client, url) for url in urls_to_check]
        results = await asyncio.gather(*tasks)

        found = [r for r in results if r is not None]

        if found:
            logger.debug("Found %s app paths: %s", len(found), [u for u, _ in found])

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
            main_headers = await self._fetch_headers(full_main_url)
            self._last_main_headers = main_headers
            main_tech = await self.analyze_html(main_html, full_main_url, main_headers)
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

        # Analyze discovered subdomains using headers from probes (no redundant GETs)
        if subdomains:
            logger.debug("Analyzing %s subdomains...", len(subdomains))
            tasks = [self.analyze_html("", url, headers) for url, headers in subdomains]
            subdomain_results = await asyncio.gather(*tasks, return_exceptions=True)

            for (url, _headers), tech in zip(subdomains, subdomain_results):
                if isinstance(tech, Exception):
                    logger.error("Error analyzing %s: %s", url, tech)
                    continue
                if tech.technologies:
                    subdomain_name = urlparse(url).netloc
                    results[subdomain_name] = tech

        # Analyze discovered app paths using headers from probes (no redundant GETs)
        if app_paths:
            logger.debug("Analyzing %s app paths...", len(app_paths))
            tasks = [self.analyze_html("", url, headers) for url, headers in app_paths]
            path_results = await asyncio.gather(*tasks, return_exceptions=True)

            for (url, _headers), tech in zip(app_paths, path_results):
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
