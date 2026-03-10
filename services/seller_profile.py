"""Seller website profile enrichment built from a small Firecrawl scrape set."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import urlparse, urlunparse

from openai import AsyncOpenAI

from config import get_settings
from services.collect import get_shared_http_client
from services.firecrawl import FirecrawlService

logger = logging.getLogger(__name__)


class SellerProfileService:
    """Build a compact seller profile from a website using map + 3 scrapes."""

    MAX_PROFILE_SCRAPES = 3

    _EXCLUDED_PATH_TERMS = (
        "/blog", "/news", "/press", "/careers", "/jobs", "/privacy", "/terms",
        "/legal", "/contact", "/login", "/signin", "/sign-in", "/signup",
        "/sign-up", "/register", "/webinar", "/events", "/podcast",
    )

    _BUCKET_PATTERNS: dict[str, tuple[tuple[str, int], ...]] = {
        "product": (
            ("/product", 10), ("/platform", 10), ("/features", 9),
            ("/software", 8), ("/service", 7), ("/how-it-works", 7),
            ("/overview", 6), ("/integrations", 5), ("/docs", 3),
        ),
        "audience": (
            ("/solutions", 10), ("/use-cases", 10), ("/use-cases", 10),
            ("/industries", 9), ("/customers", 8), ("/for-", 7),
            ("/teams", 7), ("/roles", 7),
        ),
        "proof": (
            ("/customers", 10), ("/case-studies", 10), ("/testimonials", 9),
            ("/pricing", 8), ("/about", 6), ("/why-", 5), ("/compare", 5),
        ),
    }

    def __init__(self, firecrawl_service: FirecrawlService | None = None):
        self.settings = get_settings()
        self.firecrawl = firecrawl_service or FirecrawlService()
        self.client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=45.0,
        )

    async def build_profile(self, company_website: str, company_name: str = "") -> dict:
        """Return a structured seller profile derived from the seller's public website."""
        normalized = self._normalize_base_url(company_website)
        client = await get_shared_http_client()

        map_task = self.firecrawl._map_site(client, normalized)
        sitemap_task = self.firecrawl._fetch_sitemap(client, normalized)
        mapped_urls, sitemap_urls = await asyncio.gather(map_task, sitemap_task, return_exceptions=True)

        candidates: list[str] = [normalized]
        if isinstance(mapped_urls, list):
            candidates.extend(mapped_urls)
        if isinstance(sitemap_urls, dict):
            candidates.extend(v for v in sitemap_urls.values() if v)

        selected_urls = self.select_profile_urls(normalized, candidates)
        scrape_tasks = [self.firecrawl._scrape_url(client, url) for url in selected_urls]
        raw_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)

        scraped_pages: list[dict[str, str]] = []
        for url, result in zip(selected_urls, raw_results):
            if isinstance(result, Exception) or not result:
                continue
            scraped_pages.append({"url": url, "content": result[:6000]})

        if not scraped_pages:
            return {
                "one_liner": "",
                "problems_solved": [],
                "target_personas": [],
                "target_industries": [],
                "target_company_sizes": [],
                "differentiators": [],
                "proof_points": [],
                "keywords_to_seek": [],
                "notes": "",
                "source_pages": selected_urls[:1],
            }

        synthesized = await self._synthesize_profile(
            company_name=company_name or self._default_company_name(normalized),
            company_website=normalized,
            scraped_pages=scraped_pages,
        )
        synthesized["source_pages"] = [page["url"] for page in scraped_pages]
        return synthesized

    def select_profile_urls(self, base_url: str, urls: list[str]) -> list[str]:
        """Pick homepage + 2 high-signal subpages for seller profiling."""
        canonical_base = self._normalize_base_url(base_url)
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            canonical = self._canonicalize_url(url)
            if not canonical or canonical in seen:
                continue
            if urlparse(canonical).netloc != urlparse(canonical_base).netloc:
                continue
            seen.add(canonical)
            deduped.append(canonical)

        selected = [canonical_base]
        selected_set = {canonical_base}

        for bucket in ("product", "audience", "proof"):
            best_url = ""
            best_score = -1
            for url in deduped:
                if url in selected_set:
                    continue
                score = self._score_url(url, bucket)
                if score > best_score:
                    best_score = score
                    best_url = url
            if best_url and best_score > 0:
                selected.append(best_url)
                selected_set.add(best_url)
            if len(selected) >= self.MAX_PROFILE_SCRAPES:
                return selected[:self.MAX_PROFILE_SCRAPES]

        for url in deduped:
            if url in selected_set or self._is_excluded(url):
                continue
            selected.append(url)
            if len(selected) >= self.MAX_PROFILE_SCRAPES:
                break

        return selected[:self.MAX_PROFILE_SCRAPES]

    def _score_url(self, url: str, bucket: str) -> int:
        if self._is_excluded(url):
            return -1
        path = (urlparse(url).path or "/").lower()
        score = 0
        for token, weight in self._BUCKET_PATTERNS.get(bucket, ()):
            if token in path:
                score = max(score, weight)
        if path.count("/") <= 2:
            score += 1
        if len(path) <= 40:
            score += 1
        return score

    def _is_excluded(self, url: str) -> bool:
        path = (urlparse(url).path or "/").lower()
        return any(term in path for term in self._EXCLUDED_PATH_TERMS)

    async def _synthesize_profile(
        self,
        *,
        company_name: str,
        company_website: str,
        scraped_pages: list[dict[str, str]],
    ) -> dict:
        if not self.settings.openrouter_api_key:
            return self._fallback_profile(scraped_pages)

        page_blocks = []
        for page in scraped_pages:
            page_blocks.append(f"URL: {page['url']}\n\n{page['content']}")

        prompt = f"""
You are extracting a compact seller profile from the seller's own public website.
Use only the provided site excerpts. If a field is not supported by the source text, leave it blank or use [].

Return JSON only with exactly these keys:
- one_liner: string
- problems_solved: string[]
- target_personas: string[]
- target_industries: string[]
- target_company_sizes: string[]
- differentiators: string[]
- proof_points: string[]
- keywords_to_seek: string[]
- notes: string

Rules:
- Keep lists short: 3-6 items max.
- Problems solved should be plain English pain statements, not feature names.
- target_personas should be buyer titles or role labels.
- target_industries should be buyer verticals only if clearly supported.
- target_company_sizes should be things like SMB, Mid-market, Enterprise only if clearly supported.
- differentiators should be claims the site actually makes.
- proof_points should be concrete evidence like customer outcomes, logos, certifications, integrations, or quantified claims.
- keywords_to_seek should be account-research terms that would suggest fit or pain for this seller.
- notes should be one short sentence about the likely messaging angle.

Company: {company_name}
Website: {company_website}

Site excerpts:

{chr(10).join(page_blocks)}
""".strip()

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.research_model,
                max_tokens=1200,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            choices = getattr(response, "choices", None) or []
            if not choices or not getattr(choices[0], "message", None):
                return self._fallback_profile(scraped_pages)
            content = getattr(choices[0].message, "content", "") or ""
            payload = json.loads(self._extract_json(content))
            return self._sanitize_profile(payload)
        except Exception:
            logger.warning("Seller profile synthesis failed for %s", company_website, exc_info=True)
            return self._fallback_profile(scraped_pages)

    def _sanitize_profile(self, payload: dict) -> dict:
        def _clean_text(value: object, *, limit: int = 240) -> str:
            if not isinstance(value, str):
                return ""
            text = " ".join(value.split()).strip()
            return text[:limit]

        def _clean_list(value: object, *, max_items: int) -> list[str]:
            if not isinstance(value, list):
                return []
            out: list[str] = []
            seen: set[str] = set()
            for item in value:
                cleaned = _clean_text(item, limit=120)
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(cleaned)
                if len(out) >= max_items:
                    break
            return out

        return {
            "one_liner": _clean_text(payload.get("one_liner")),
            "problems_solved": _clean_list(payload.get("problems_solved"), max_items=6),
            "target_personas": _clean_list(payload.get("target_personas"), max_items=6),
            "target_industries": _clean_list(payload.get("target_industries"), max_items=6),
            "target_company_sizes": _clean_list(payload.get("target_company_sizes"), max_items=4),
            "differentiators": _clean_list(payload.get("differentiators"), max_items=6),
            "proof_points": _clean_list(payload.get("proof_points"), max_items=6),
            "keywords_to_seek": _clean_list(payload.get("keywords_to_seek"), max_items=8),
            "notes": _clean_text(payload.get("notes"), limit=200),
        }

    def _fallback_profile(self, scraped_pages: list[dict[str, str]]) -> dict:
        homepage_text = scraped_pages[0]["content"] if scraped_pages else ""
        summary = self._plain_text(homepage_text)[:220]
        return {
            "one_liner": summary,
            "problems_solved": [],
            "target_personas": [],
            "target_industries": [],
            "target_company_sizes": [],
            "differentiators": [],
            "proof_points": [],
            "keywords_to_seek": [],
            "notes": "",
        }

    def _extract_json(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped

        start = stripped.find("{")
        if start == -1:
            raise ValueError("No JSON object found")

        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(stripped)):
            ch = stripped[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return stripped[start:idx + 1]
        raise ValueError("Unbalanced JSON object")

    def _normalize_base_url(self, url: str) -> str:
        parsed = urlparse(url if url.startswith(("http://", "https://")) else f"https://{url}")
        return self._canonicalize_url(f"{parsed.scheme}://{parsed.netloc}")

    def _canonicalize_url(self, url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url if url.startswith(("http://", "https://")) else f"https://{url}")
        if not parsed.netloc:
            return ""
        clean_path = re.sub(r"/{2,}", "/", parsed.path or "/")
        if clean_path != "/" and clean_path.endswith("/"):
            clean_path = clean_path[:-1]
        final_path = "" if clean_path == "/" else (clean_path or "")
        return urlunparse((parsed.scheme or "https", parsed.netloc, final_path, "", "", ""))

    def _default_company_name(self, base_url: str) -> str:
        domain = urlparse(base_url).netloc.replace("www.", "")
        return domain.split(".")[0].replace("-", " ").replace("_", " ").title()

    def _plain_text(self, text: str) -> str:
        text = re.sub(r"`{1,3}.*?`{1,3}", " ", text, flags=re.S)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
        text = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", text)
        text = re.sub(r"[#>*_]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
