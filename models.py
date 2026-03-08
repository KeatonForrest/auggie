"""models.py - Pydantic data models for request/response validation."""

from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime


class ResearchRequest(BaseModel):
    """Input for a research request."""
    company_url: HttpUrl
    product_context: str = ""  # Will be populated from user profile


class ScrapedContent(BaseModel):
    """Data returned from Firecrawl after scraping a company's website."""
    homepage: Optional[str] = None
    homepage_html: Optional[str] = None
    about: Optional[str] = None
    careers: Optional[str] = None
    blog: Optional[str] = None
    job_postings: Optional[str] = None
    additional_pages: Optional[str] = None
    site_structure: Optional[dict[str, str]] = None
    news: Optional[str] = None
    investor_relations: Optional[str] = None
    edgar_filings: Optional[str] = None
    federal_regulations: Optional[str] = None
    firmographics: Optional[str] = None
    web_mentions: Optional[str] = None


class DetectedTechnology(BaseModel):
    """A single technology detected on a website."""
    name: str
    version: Optional[str] = None
    category: Optional[str] = None
    confidence: Optional[int] = None
    signal_quality: Optional[float] = None       # 0.0-1.0 weighted quality score
    matched_patterns: Optional[list[str]] = None  # e.g. ["header", "script"]


class StackArchetype(BaseModel):
    """A composite stack pattern detected from multiple technologies."""
    name: str
    confidence: float            # 0.0-1.0
    matched_technologies: list[str]
    description: Optional[str] = None


class TechStack(BaseModel):
    """Technologies detected on a website."""
    technologies: list[DetectedTechnology] = []
    scan_url: Optional[str] = None
    archetypes: Optional[list[StackArchetype]] = None

    # Categories that are noise or false positives — exclude from prompts
    _EXCLUDED_CATEGORIES = {"Cryptominers"}

    def to_prompt_text(self) -> str:
        """Format for inclusion in Claude's prompt."""
        if not self.technologies:
            return "No technologies detected."

        lines = []
        for tech in self.technologies:
            if tech.confidence is not None and tech.confidence < 75:
                continue
            if tech.category and any(c.strip() in self._EXCLUDED_CATEGORIES for c in tech.category.split(",")):
                continue
            entry = f"- {tech.name}"
            if tech.version:
                entry += f" {tech.version}"
            if tech.category:
                entry += f" ({tech.category})"
            lines.append(entry)

        if self.archetypes:
            high_conf = [a for a in self.archetypes if a.confidence >= 0.5]
            if high_conf:
                lines.append("")
                lines.append("Stack Archetypes:")
                for arch in high_conf:
                    desc = f" - {arch.description}" if arch.description else ""
                    lines.append(f"- {arch.name} (confidence: {arch.confidence:.0%}){desc}")

        return "\n".join(lines)


class DNSProfile(BaseModel):
    domain: str
    ns_provider: Optional[str] = None
    mx_provider: Optional[str] = None
    has_spf: bool = False
    has_dkim: bool = False
    has_dmarc: bool = False
    dmarc_policy: Optional[str] = None
    txt_signals: list[str] = []
    cloud_provider_hints: list[str] = []


class SSLProfile(BaseModel):
    domain: str
    issuer: Optional[str] = None
    expiry_days: Optional[int] = None
    san_count: int = 0
    is_wildcard: bool = False
    automation_inferred: bool = False


class SecurityPosture(BaseModel):
    score: int = 0
    present: list[str] = []
    missing: list[str] = []
    grade: str = "F"


class RobotsSignals(BaseModel):
    api_paths: list[str] = []
    admin_paths: list[str] = []
    crawl_delay: Optional[float] = None
    interesting_disallows: list[str] = []


class InfrastructureSignals(BaseModel):
    """Collapsed infrastructure analysis: DNS + SSL + security headers + robots.txt."""
    domain: str
    # DNS
    ns_provider: Optional[str] = None
    mx_provider: Optional[str] = None
    has_spf: bool = False
    has_dkim: bool = False
    has_dmarc: bool = False
    dmarc_policy: Optional[str] = None
    cloud_provider_hints: list[str] = []
    # SSL
    ssl_issuer: Optional[str] = None
    ssl_expiry_days: Optional[int] = None
    ssl_san_count: int = 0
    ssl_is_wildcard: bool = False
    ssl_automation_inferred: bool = False
    # Security headers
    security_score: int = 0
    security_present: list[str] = []
    security_missing: list[str] = []
    security_grade: str = "F"
    # Robots.txt
    robots_api_paths: list[str] = []
    robots_admin_paths: list[str] = []
    robots_crawl_delay: Optional[float] = None
    robots_interesting_disallows: list[str] = []



class TechMention(BaseModel):
    name: str
    category: str
    count: int = 1


class JobSignals(BaseModel):
    tech_mentions: list[TechMention] = []
    role_types: list[str] = []
    role_type_counts: dict[str, int] = {}
    seniority_distribution: dict[str, int] = {}
    initiative_signals: list[str] = []
    delivery_model_signals: list[str] = []
    capacity_signals: list[str] = []
    capability_gap_signals: list[str] = []
    total_roles_parsed: int = 0


class PainInference(BaseModel):
    rule_id: str
    title: str
    description: str
    severity: str
    evidence: list[str]
    confidence: int = 0
    category: str = ""


class SellerContext(BaseModel):
    product_type: str = "saas"
    problems_solved: str = ""


class SignalBundle(BaseModel):
    domain: str = ""
    tech_by_domain: dict = {}
    infra: Optional[InfrastructureSignals] = None
    job_signals: Optional[JobSignals] = None

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, **data):
        """Accept legacy dns_profile/ssl_profile/security_posture/robots_signals kwargs
        and fold them into a single InfrastructureSignals object."""
        dns = data.pop("dns_profile", None)
        ssl_p = data.pop("ssl_profile", None)
        sec = data.pop("security_posture", None)
        rob = data.pop("robots_signals", None)

        if data.get("infra") is None and any(x is not None for x in (dns, ssl_p, sec, rob)):
            domain = data.get("domain", "")
            infra_kwargs: dict = {"domain": domain}
            if dns:
                infra_kwargs["ns_provider"] = dns.ns_provider
                infra_kwargs["mx_provider"] = dns.mx_provider
                infra_kwargs["has_spf"] = dns.has_spf
                infra_kwargs["has_dkim"] = dns.has_dkim
                infra_kwargs["has_dmarc"] = dns.has_dmarc
                infra_kwargs["dmarc_policy"] = dns.dmarc_policy
                infra_kwargs["cloud_provider_hints"] = list(dns.cloud_provider_hints)
                if not domain and dns.domain:
                    infra_kwargs["domain"] = dns.domain
            if ssl_p:
                infra_kwargs["ssl_issuer"] = ssl_p.issuer
                infra_kwargs["ssl_expiry_days"] = ssl_p.expiry_days
                infra_kwargs["ssl_san_count"] = ssl_p.san_count
                infra_kwargs["ssl_is_wildcard"] = ssl_p.is_wildcard
                infra_kwargs["ssl_automation_inferred"] = ssl_p.automation_inferred
            if sec:
                infra_kwargs["security_score"] = sec.score
                infra_kwargs["security_present"] = list(sec.present)
                infra_kwargs["security_missing"] = list(sec.missing)
                infra_kwargs["security_grade"] = sec.grade
            if rob:
                infra_kwargs["robots_api_paths"] = list(rob.api_paths)
                infra_kwargs["robots_admin_paths"] = list(rob.admin_paths)
                infra_kwargs["robots_crawl_delay"] = rob.crawl_delay
                infra_kwargs["robots_interesting_disallows"] = list(rob.interesting_disallows)
            data["infra"] = InfrastructureSignals(**infra_kwargs)

        super().__init__(**data)


_APP_PREFIXES = ("app.", "dashboard.", "portal.", "console.", "platform.", "my.", "admin.", "web.")


def _classify_domain(domain: str) -> str:
    """Classify a domain as Product/Application, API, or Marketing Site."""
    normalized = domain.lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    if normalized.startswith(_APP_PREFIXES):
        return "Product/Application"
    if normalized.startswith("api."):
        return "API"
    return "Marketing Site"


def format_multi_domain_tech(tech_by_domain: dict[str, "TechStack"]) -> str:
    """Format technology results from multiple domains for Claude's prompt."""
    if not tech_by_domain:
        return "No technologies detected."

    sections = []

    for domain, tech_stack in tech_by_domain.items():
        if not tech_stack.technologies:
            continue

        domain_type = _classify_domain(domain)
        section = f"**{domain}** ({domain_type}):\n{tech_stack.to_prompt_text()}"
        sections.append(section)

    return "\n\n".join(sections)


def format_tech_by_tier(tech_by_domain: dict[str, "TechStack"]) -> tuple[str, str]:
    """Split tech by domain into tier1 (Product/App + API) and tier3 (Marketing Site) text.

    Returns (tier1_text, tier3_text). Either may be empty string.
    """
    if not tech_by_domain:
        return ("", "")

    tier1_sections = []
    tier3_sections = []

    for domain, tech_stack in tech_by_domain.items():
        if not tech_stack.technologies:
            continue

        domain_type = _classify_domain(domain)
        section = f"**{domain}** ({domain_type}):\n{tech_stack.to_prompt_text()}"

        if domain_type in ("Product/Application", "API"):
            tier1_sections.append(section)
        else:
            tier3_sections.append(section)

    return ("\n\n".join(tier1_sections), "\n\n".join(tier3_sections))


class ResearchDocument(BaseModel):
    """The final Account Research Document."""
    id: Optional[int] = None
    company_url: str
    company_name: str
    slug: Optional[str] = None
    created_at: datetime

    # AI-generated sections
    company_overview: str
    projects_initiatives: str
    confirmed_tech_stack: str
    hiring_signals: str
    business_problems: str
    existential_data_points: str = ""
    before_scenario: str = ""
    pvp_seed: str = ""
    required_capabilities: str = ""
    product_fit: str
    talking_points: str
    recent_news: str = ""
    key_contacts: str = ""
    recommended_contacts: str = ""
    information_gaps: str

    # Opportunity Scoring (Full tier only)
    opportunity_score: Optional[int] = None  # 0-100 composite score
    pain_score: Optional[int] = None         # 0-100 (40% weight)
    fit_score: Optional[int] = None          # 0-100 (35% weight)
    timing_score: Optional[int] = None       # 0-100 (25% weight)
    score_summary: Optional[str] = None      # Brief justification
    pain_evidence: Optional[str] = None      # Bullet list of pain signals
    fit_evidence: Optional[str] = None       # Bullet list of fit signals
    timing_evidence: Optional[str] = None    # Bullet list of timing signals

    # Model metadata
    thinking_content: Optional[str] = None
    model_used: Optional[str] = None

    full_markdown: str


class ResearchResponse(BaseModel):
    """API response wrapper."""
    success: bool
    document: Optional[ResearchDocument] = None
    error: Optional[str] = None
