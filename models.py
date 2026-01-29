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
    news: Optional[str] = None
    investor_relations: Optional[str] = None
    edgar_filings: Optional[str] = None
    reviews: Optional[str] = None
    federal_regulations: Optional[str] = None


class DetectedTechnology(BaseModel):
    """A single technology detected by Wappalyzer."""
    name: str
    version: Optional[str] = None
    category: Optional[str] = None
    confidence: Optional[int] = None


class TechStack(BaseModel):
    """Technologies detected on a website via Wappalyzer."""
    technologies: list[DetectedTechnology] = []
    scan_url: Optional[str] = None

    def to_prompt_text(self) -> str:
        """Format for inclusion in Claude's prompt."""
        if not self.technologies:
            return "No technologies detected."

        lines = []
        for tech in self.technologies:
            entry = f"- {tech.name}"
            if tech.version:
                entry += f" {tech.version}"
            if tech.category:
                entry += f" ({tech.category})"
            lines.append(entry)

        return "\n".join(lines)


def format_multi_domain_tech(tech_by_domain: dict[str, "TechStack"]) -> str:
    """Format technology results from multiple domains for Claude's prompt."""
    if not tech_by_domain:
        return "No technologies detected."

    sections = []
    app_prefixes = ("app.", "dashboard.", "portal.", "console.", "platform.", "my.", "admin.", "web.")

    for domain, tech_stack in tech_by_domain.items():
        if not tech_stack.technologies:
            continue

        if domain.startswith(app_prefixes):
            domain_type = "Product/Application"
        elif domain.startswith("api."):
            domain_type = "API"
        else:
            domain_type = "Marketing Site"

        section = f"**{domain}** ({domain_type}):\n{tech_stack.to_prompt_text()}"
        sections.append(section)

    return "\n\n".join(sections)


class ResearchDocument(BaseModel):
    """The final Account Research Document."""
    id: Optional[int] = None
    company_url: str
    company_name: str
    created_at: datetime

    # AI-generated sections
    company_overview: str
    projects_initiatives: str
    confirmed_tech_stack: str
    hiring_signals: str
    business_problems: str
    existential_data_points: str = ""
    product_fit: str
    talking_points: str
    recent_news: str = ""
    key_contacts: str = ""
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

    full_markdown: str


class ResearchResponse(BaseModel):
    """API response wrapper."""
    success: bool
    document: Optional[ResearchDocument] = None
    error: Optional[str] = None
