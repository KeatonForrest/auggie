"""Perplexity search service — seller-shaped web research.

Runs 3 queries per company, shaped by the seller's product category.
Non-fatal: returns empty results on any failure. Cached for 24 hours.
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86400  # 24 hours
QUERY_TIMEOUT = 10  # seconds per query
API_URL = "https://api.perplexity.ai/chat/completions"

# ── Query templates shaped by seller category ──

_CATEGORY_QUERIES: dict[str, list[str]] = {
    "database": [
        '"{company}" database migration scalability challenges',
        '"{company}" data infrastructure engineering blog',
        '"{company}" recent news funding growth 2025 2026',
    ],
    "fintech": [
        '"{company}" payment processing compliance PCI challenges',
        '"{company}" financial infrastructure banking technology',
        '"{company}" recent news funding regulatory 2025 2026',
    ],
    "healthtech": [
        '"{company}" healthcare integration HIPAA compliance challenges',
        '"{company}" clinical data EHR technology infrastructure',
        '"{company}" recent news funding growth 2025 2026',
    ],
    "martech": [
        '"{company}" marketing technology stack CDP analytics challenges',
        '"{company}" customer data attribution personalization',
        '"{company}" recent news funding growth 2025 2026',
    ],
    "devtools": [
        '"{company}" developer experience CI/CD infrastructure challenges',
        '"{company}" engineering platform deployment observability',
        '"{company}" recent news funding growth 2025 2026',
    ],
}

_DEFAULT_QUERIES = [
    '"{company}" recent news developments 2025 2026',
    '"{company}" technology stack infrastructure engineering',
    '"{company}" challenges problems scaling',
]


@dataclass
class PerplexityResult:
    query: str
    content: str
    citations: list[str] = field(default_factory=list)


@dataclass
class PerplexityResults:
    results: list[PerplexityResult] = field(default_factory=list)
    seller_category: str = ""
    cached: bool = False

    @classmethod
    def empty(cls) -> "PerplexityResults":
        return cls()

    def as_text(self) -> str:
        """Format results for prompt injection."""
        if not self.results:
            return ""
        parts = []
        for r in self.results:
            section = f"Query: {r.query}\n{r.content}"
            if r.citations:
                section += "\nSources: " + ", ".join(r.citations[:3])
            parts.append(section)
        return "\n\n---\n\n".join(parts)


# ── In-memory cache (per-process, good enough for Railway single-instance) ──
_cache: dict[str, tuple[float, PerplexityResults]] = {}


def _cache_key(domain: str, seller_category: str) -> str:
    raw = f"{domain.lower()}:{seller_category}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached(key: str) -> Optional[PerplexityResults]:
    if key in _cache:
        ts, results = _cache[key]
        if time.time() - ts < CACHE_TTL_SECONDS:
            return results
        del _cache[key]
    return None


def _save_cached(key: str, results: PerplexityResults) -> None:
    _cache[key] = (time.time(), results)
    # Evict old entries when cache grows too large
    if len(_cache) > 500:
        cutoff = time.time() - CACHE_TTL_SECONDS
        expired = [k for k, (ts, _) in _cache.items() if ts < cutoff]
        for k in expired:
            del _cache[k]


def get_queries(company_name: str, seller_category: str = "") -> list[str]:
    """Build seller-shaped search queries for a company."""
    templates = _CATEGORY_QUERIES.get(seller_category, _DEFAULT_QUERIES)
    return [t.replace("{company}", company_name) for t in templates]


async def search(
    domain: str,
    company_name: str,
    seller_category: str = "",
) -> PerplexityResults:
    """Run seller-shaped Perplexity queries for a company.

    Returns empty results on any failure (non-fatal).
    """
    settings = get_settings()
    if not settings.perplexity_api_key:
        return PerplexityResults.empty()

    key = _cache_key(domain, seller_category)
    cached = _get_cached(key)
    if cached is not None:
        cached.cached = True
        return cached

    queries = get_queries(company_name, seller_category)
    results: list[PerplexityResult] = []

    try:
        overall_timeout = QUERY_TIMEOUT * len(queries) + 5
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
            tasks = [_single_query(client, settings.perplexity_api_key, q) for q in queries]
            raw_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=overall_timeout,
            )
            for q, r in zip(queries, raw_results):
                if isinstance(r, PerplexityResult):
                    results.append(r)
                elif isinstance(r, Exception):
                    logger.warning("Perplexity query failed: %s — %s", q[:60], r)
    except (TimeoutError, asyncio.TimeoutError):
        logger.warning("Perplexity search timed out for %s", domain)
    except Exception as e:
        logger.warning("Perplexity search failed for %s: %s", domain, e)

    out = PerplexityResults(results=results, seller_category=seller_category)
    if results:
        _save_cached(key, out)
    return out


async def _single_query(client: httpx.AsyncClient, api_key: str, query: str) -> PerplexityResult:
    """Execute a single Perplexity sonar query."""
    resp = await client.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "sonar",
            "messages": [{"role": "user", "content": query}],
        },
    )
    resp.raise_for_status()
    data = resp.json()

    content = ""
    citations = []
    choices = data.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
    citations = data.get("citations", [])

    return PerplexityResult(query=query, content=content, citations=citations)
