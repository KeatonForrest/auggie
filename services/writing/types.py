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
    "fintech": [
        "payments", "banking", "lending", "kyc", "aml", "billing platform",
        "payment processing", "financial services", "neobank", "fintech",
        "transaction", "pci", "card issuing", "underwriting", "regtech",
    ],
    "healthtech": [
        "healthcare", "ehr", "telehealth", "hipaa", "clinical", "patient",
        "health tech", "healthtech", "medical device", "digital health",
        "electronic health record", "health information", "care coordination",
    ],
    "martech": [
        "marketing automation", "cdp", "attribution", "personalization",
        "customer data platform", "campaign management", "martech",
        "marketing platform", "email marketing", "lead scoring",
        "marketing analytics", "demand generation",
    ],
    "devtools": [
        "developer tools", "ci/cd", "observability", "apm", "kubernetes",
        "devtools", "developer experience", "build system", "deployment",
        "infrastructure as code", "monitoring", "logging", "container",
        "developer platform",
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
    "fintech": {
        "blocked_patterns": [
            "frontend framework", "react", "vue", "angular", "svelte",
            "cdn", "content delivery", "seo", "page speed",
            "marketing automation", "tag manager", "google tag",
        ],
        "linkage_overrides": [
            "payment flow", "transaction", "pci", "financial data",
            "billing integration", "payment processing", "ledger",
        ],
        "prompt_constraint": (
            "Frontend framework, CDN, SEO, and marketing automation angles "
            "are INVALID for a fintech seller unless the talking point "
            "explicitly ties them to a payment flow, transaction processing, "
            "PCI compliance, or financial data consequence."
        ),
    },
    "healthtech": {
        "blocked_patterns": [
            "frontend framework", "react", "vue", "angular",
            "cdn", "content delivery", "e-commerce", "ecommerce",
            "marketing automation", "seo", "tag manager",
        ],
        "linkage_overrides": [
            "patient data", "ehr integration", "clinical workflow", "hipaa",
            "health record", "care coordination", "telehealth",
        ],
        "prompt_constraint": (
            "Frontend framework, CDN, e-commerce, and marketing automation "
            "angles are INVALID for a healthtech seller unless the talking "
            "point explicitly ties them to patient data, EHR integration, "
            "clinical workflow, or HIPAA compliance."
        ),
    },
    "martech": {
        "blocked_patterns": [
            "db migration", "database migration", "kubernetes", "k8s",
            "ci/cd", "devops", "security scanning", "vulnerability",
            "infrastructure as code", "terraform",
        ],
        "linkage_overrides": [
            "customer data", "campaign performance", "lead scoring",
            "marketing analytics", "attribution", "conversion",
        ],
        "prompt_constraint": (
            "Database migration, Kubernetes, CI/CD, DevOps, and security "
            "scanning angles are INVALID for a martech seller unless the "
            "talking point explicitly ties them to customer data, campaign "
            "performance, lead scoring, or marketing analytics."
        ),
    },
    "devtools": {
        "blocked_patterns": [
            "marketing automation", "seo", "e-commerce", "ecommerce",
            "crm", "salesforce", "hubspot", "customer data platform",
            "cdp", "campaign management",
        ],
        "linkage_overrides": [
            "developer experience", "build time", "pipeline",
            "infrastructure", "deployment velocity", "developer productivity",
        ],
        "prompt_constraint": (
            "Marketing automation, SEO, e-commerce, and CRM angles are "
            "INVALID for a devtools seller unless the talking point "
            "explicitly ties them to developer experience, build time, "
            "CI/CD pipeline, or infrastructure concerns."
        ),
    },
}
