"""types.py - Shared dataclasses and constants for the writing service."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class GenerationContext:
    """All context needed by a channel strategy to build prompts."""

    document: Any  # ResearchDocument
    product_context: str
    report: str
    product_type: str = "saas"
    product_category: str = ""
    retrieved_materials: str = ""
    seller_company: str = ""
    problems_solved: str = ""
    persona_context: str = ""
    custom_signals: str = ""
    opportunity_score: Optional[int] = None
    has_persona: bool = False
    linkedin_context: dict = field(default_factory=dict)
    mode: str = ""
    company_name: str = ""
    pea_selector_enabled: bool = False


@dataclass
class ValidationResult:
    """Result of validating generated output."""

    is_valid: bool
    error_reason: str = ""
    error_code: str = ""


@dataclass
class GenerationTelemetry:
    """Structured telemetry for a generation call."""

    channel: str = ""
    model: str = ""
    latency_ms: int = 0
    retry_count: int = 0
    validation_fail_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    parse_success: bool = False
    repair_attempted: bool = False
    repair_success: bool = False
    word_limit_pass: bool = False
    cta_rescued: bool = False
    relevance_reprompted: bool = False


# ---------------------------------------------------------------------------
# Constants shared across the package
# ---------------------------------------------------------------------------

WORD_LIMITS = {1: 75, 2: 100, 3: 60}
LINKEDIN_WORD_LIMITS = {"dm": 90, "connection_request": 45}

_CATEGORY_KEYWORDS = {
    "database": [
        "database", "db ", "data warehouse", "data lake", "sql", "nosql",
        "mongodb", "postgres", "postgresql", "mysql", "redis", "dynamodb",
        "cassandra", "cockroachdb", "data platform", "data infrastructure",
        "vector database", "graph database", "time-series", "olap", "oltp",
    ],
}

_CATEGORY_DENYLISTS = {
    "database": {
        "blocked_patterns": [
            "cdn", "content delivery", "cloudflare", "fastly", "akamai",
            "frontend framework", "react", "vue", "angular", "svelte",
            "next.js", "nuxt", "jquery", "bootstrap", "tailwind",
            "css", "scss", "webpack", "vite", "bundler",
            "seo", "page speed", "tag manager", "google tag",
        ],
        "linkage_overrides": [
            "database bottleneck", "db bottleneck", "query performance",
            "api latency", "data pipeline", "backend performance",
            "read replica", "write throughput", "connection pool",
            "slow queries", "index", "migration", "data-intensive",
        ],
        "prompt_constraint": (
            "CDN, frontend framework, CSS tooling, and marketing automation "
            "angles are INVALID for a database seller unless the talking point "
            "explicitly ties them to a database bottleneck, query performance "
            "issue, or data layer consequence."
        ),
    },
}
