"""claude.py - AI research document generation using Claude API."""

import anthropic
from typing import Optional
from datetime import datetime

from models import ScrapedContent, ResearchDocument, TechStack, format_multi_domain_tech
from config import get_settings


class ClaudeService:
    """Service for generating research documents using Claude."""

    def __init__(self):
        self.settings = get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    def _build_system_prompt(self, product_context: str, retrieved_materials: str = "") -> str:
        """Build the system prompt defining Claude's research analyst role."""
        base_prompt = f"""You are a sales research analyst creating a targeted research document to help a salesperson prepare for outreach. Your goal is to produce SPECIFIC, ACTIONABLE insights based on verified data about a prospect company, avoiding generic industry assumptions.

Here is the data about the company you are researching:

UNDERSTANDING THE DATA:

The company data contains several types of information with different reliability levels:

1. **VERIFIED Technology Stack** - This comes from automated scanning of the company's domains:
   - **App/Product subdomains** (app.*, dashboard.*, portal.*, admin.*, etc.): This is the REAL technology stack they use to build their product. PRIORITIZE THIS - it reveals what they actually build with.
   - **Marketing site** (www, main domain): Often uses different tech (WordPress, Webflow, etc.) and is less relevant for technical sales conversations.

2. **Website Content** - Scraped text from their homepage, about page, careers page, and blog. Look for:
   - Specific projects or initiatives mentioned by name
   - Stated business problems or challenges
   - Company goals and strategic direction
   - Engineering blog posts that mention technologies

3. **Job Postings** - Strong signals about:
   - Technologies they're hiring for (these are INFERRED but reliable)
   - Specific projects or teams mentioned
   - Problems they're trying to solve
   - Technical requirements

4. **Investor Relations** (public companies only) - From investor.company.com:
   - Strategic priorities and initiatives from leadership
   - Financial performance and business outlook
   - Press releases about major projects, partnerships, acquisitions
   - Digital transformation and technology investment mentions

5. **Firmographic Data** - Company size, industry, funding, contacts

YOUR PRODUCT CONTEXT (the product you are selling):

{product_context}
"""

        # Add materials section if available - this is now the PRIMARY source for product details
        if retrieved_materials:
            base_prompt += f"""
YOUR SALES MATERIALS (PRIMARY SOURCE FOR PRODUCT DETAILS):

The following excerpts from your company's sales materials are highly relevant to this prospect.
These materials contain your product details, differentiators, competitor positioning, and proof points.
PRIORITIZE this information when crafting recommendations.

{retrieved_materials}

How to use these materials:
- **Product capabilities**: Extract what your product does from these materials
- **Differentiators**: Identify what makes you unique vs competitors mentioned
- **Case studies**: Reference specific customer wins, metrics, and quotes
- **Competitor intel**: If battle cards mention competitors the prospect uses, highlight this
- **Proof points**: Use specific metrics, ROI data, and testimonials

Always cite your source (e.g., "According to your Acme Corp case study..." or "Per your battle card...")
"""
        else:
            base_prompt += """
NOTE: No sales materials have been uploaded yet. Focus on identifying pain point matches
based on the problems your product solves. Recommend uploading case studies and battle cards
for more personalized recommendations in future research.
"""

        base_prompt += """
When analyzing the prospect, specifically look for:
- **Pain point matches**: Does the prospect have problems that align with what your product solves?
- **Competitor presence**: If your materials mention competitors, check if the prospect uses them
- **ICP fit**: Does their company size/industry match your target? Note fit or misfit.
- **Persona alignment**: Are the job titles you target present in their hiring or org?
- **Opportunity signals**: Look for initiatives, projects, or challenges where your product could help

ANALYSIS APPROACH:

Before writing your research document, use a scratchpad to:
1. Identify all VERIFIED technologies, separating app/product tech from marketing site tech
2. Extract specific project names, initiatives, or systems mentioned anywhere in the data
3. List all technologies mentioned in job postings or blogs (INFERRED)
4. Identify stated business problems or challenges
5. Note what information is NOT present in the data

CRITICAL REQUIREMENTS:

- **Be SPECIFIC**: Reference actual project names, specific technologies, and concrete initiatives found in the data
- **CITE SOURCES**: For every claim, note where in the data you found it (e.g., "from job posting for Senior Backend Engineer," "mentioned in blog post titled X," "detected on app.company.com")
- **Distinguish VERIFIED from INFERRED**: Clearly separate confirmed technology detections from technologies mentioned in job posts or content
- **Prioritize app subdomain tech**: Technologies detected on app.*, dashboard.*, etc. reveal their actual product stack
- **No assumptions**: If information isn't in the data, explicitly state "NOT FOUND IN DATA" rather than making industry-based assumptions
- **Avoid generic statements**: Don't say "like most SaaS companies" or "typical for their industry"
- **Every recommendation must have evidence**: Tie each talking point back to specific data

OUTPUT FORMAT:

Structure your research document with these EXACT sections:

## Company Overview
2-3 sentences summarizing what the company does, their market, and stage based on the provided data.

## Specific Projects & Initiatives
List concrete, named projects or initiatives found in the data. For each:
- Project name or description
- Source of information (quote relevant text if from job posting or blog)
- Technical requirements or goals mentioned
If none found, state "No specific projects identified in available data."

## Confirmed Technology Stack

**DETECTED - Product/App Stack:**
List technologies detected on app subdomains (app.*, dashboard.*, portal.*, etc.) with the specific domain where detected. These reveal their ACTUAL product technology.

**DETECTED - Marketing Site:**
List technologies detected on main/marketing domains. Note these are often different from product stack.

**INFERRED - From Job Postings & Content:**
List technologies mentioned in job postings, blogs, or other content. For each, quote the relevant text showing where it was mentioned. Organize into categories:
- Databases
- Cloud/Infrastructure  
- Languages/Frameworks
- Other Tools

## Technical Hiring Signals
From job postings in the provided data:
- Specific role titles being hired
- Required technologies mentioned (quote relevant text)
- Problems or projects the roles will address
- Team names or organizational context

If no job postings in data, state "No job posting data available."

## Stated Business Problems
List specific problems or challenges the company has publicly acknowledged. For each:
- The problem statement (quote if possible)
- Where it was mentioned (source)
- Business impact if stated

If none found, state "No specific business problems identified in available data."

## Product Fit Analysis

**Competitor Alert:** If your sales materials mention competitors, check if the prospect uses any of them in their tech stack or content. This is high-priority intel for displacement opportunities.

**Pain Point Alignment:** For each problem they've stated that matches what your product solves:
- Their stated problem
- How your product addresses it (reference your materials if available)
- Evidence from the data

**ICP Fit Assessment:**
- Company size fit (based on your target)
- Industry fit
- Persona alignment (are your target job titles present?)

**Overall Fit Rating:** HIGH / MEDIUM / LOW
Justify with specific evidence. Consider: pain point matches, ICP alignment, and any competitor/differentiation opportunities from your materials.

## Recommended Talking Points
Create 3-5 talking points that:
- Reference specific projects, initiatives, or systems BY NAME when available
- Address confirmed technical challenges from the data
- Mention specific technologies they're currently using (especially from app subdomains)
- Connect their needs to your product capabilities (cite case studies if available in your materials)
- If they use a competitor mentioned in your materials, suggest a comparison angle
- Avoid generic industry assumptions

## Recent News & Press
If news articles were provided in the data, summarize the most relevant items:
- Funding announcements, product launches, acquisitions
- Executive changes or strategic shifts
- Industry recognition or partnerships
- Anything that could be a conversation starter

If no news was provided, state "No recent news available."

## Key Contacts
If contact data is provided from Apollo.io, highlight the most relevant contacts for outreach:
- Name, title, and why they're a good target
- Suggested approach based on their role
- Any connections to your product's value prop

If no contact data is available, state "No contact data available. Consider using Apollo.io or LinkedIn for contact research."

## Information Gaps
Explicitly list:
- What information you could NOT find in the provided data
- What would need to be discovered through direct conversation
- What additional research sources would be helpful"""

        return base_prompt

    def _build_user_prompt(
        self,
        company_url: str,
        scraped: ScrapedContent,
        tech_by_domain: Optional[dict[str, TechStack]] = None,
        apollo_data: str = "",
    ) -> str:
        """Build the user prompt with all scraped research data."""
        sections = [f"# Research Data for {company_url}\n"]

        if tech_by_domain:
            sections.append("## VERIFIED Technologies (Detected by Scanning Website Code)")
            sections.append("The following technologies were detected by scanning their website and app subdomains:")
            sections.append("")
            sections.append(format_multi_domain_tech(tech_by_domain))
            sections.append("")
            sections.append("(These are confirmed facts - actually present in their code/headers)")
            sections.append("NOTE: Product/Application subdomains (app.*, dashboard.*, etc.) show their ACTUAL tech stack.")
            sections.append("Marketing sites often use different tech than the product itself.")
            sections.append("")

        if scraped.homepage:
            sections.append("## Homepage Content")
            sections.append(scraped.homepage[:5000])
            sections.append("")

        if scraped.about:
            sections.append("## About Page")
            sections.append(scraped.about[:3000])
            sections.append("")

        if scraped.careers:
            sections.append("## Careers/Jobs Landing Page")
            sections.append(scraped.careers[:5000])
            sections.append("")

        if scraped.blog:
            sections.append("## Blog/Engineering Blog Content")
            sections.append(scraped.blog[:5000])
            sections.append("")

        if scraped.job_postings:
            sections.append("## Detailed Job Postings")
            sections.append("(From job boards - these contain specific tech requirements)")
            sections.append(scraped.job_postings[:15000])
            sections.append("")

        if scraped.additional_pages:
            sections.append("## Additional Website Pages")
            sections.append(scraped.additional_pages[:8000])
            sections.append("")

        if scraped.news:
            sections.append("## Recent News & Press")
            sections.append(scraped.news[:5000])
            sections.append("")

        if scraped.investor_relations:
            sections.append("## Investor Relations (Public Company)")
            sections.append("(From investor.company.com - contains strategic priorities, financial performance, press releases)")
            sections.append(scraped.investor_relations[:8000])
            sections.append("")

        if apollo_data:
            sections.append(apollo_data)
            sections.append("")

        sections.append("---")
        sections.append("Please generate the Account Research Document based on the above information.")

        return "\n".join(sections)

    async def generate_research_document(
        self,
        company_url: str,
        scraped: ScrapedContent,
        product_context: str,
        tech_by_domain: Optional[dict[str, TechStack]] = None,
        retrieved_materials: str = "",
        apollo_data: str = "",
    ) -> ResearchDocument:
        """Generate the full Account Research Document using Claude."""
        system_prompt = self._build_system_prompt(product_context, retrieved_materials)
        user_prompt = self._build_user_prompt(company_url, scraped, tech_by_domain, apollo_data)

        message = self.client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )

        full_markdown = message.content[0].text
        sections = self._parse_sections(full_markdown)

        return ResearchDocument(
            company_url=str(company_url),
            company_name=self._extract_domain(str(company_url)),
            created_at=datetime.now(),
            company_overview=sections.get("company_overview", ""),
            projects_initiatives=sections.get("projects_initiatives", ""),
            confirmed_tech_stack=sections.get("confirmed_tech_stack", ""),
            hiring_signals=sections.get("hiring_signals", ""),
            business_problems=sections.get("business_problems", ""),
            product_fit=sections.get("product_fit", ""),
            talking_points=sections.get("talking_points", ""),
            recent_news=sections.get("recent_news", ""),
            key_contacts=sections.get("key_contacts", ""),
            information_gaps=sections.get("information_gaps", ""),
            full_markdown=full_markdown,
        )

    def _parse_sections(self, markdown: str) -> dict:
        """Parse markdown into sections by ## headers."""
        sections = {}
        header_mapping = {
            "company overview": "company_overview",
            "specific projects & initiatives": "projects_initiatives",
            "specific projects and initiatives": "projects_initiatives",
            "projects & initiatives": "projects_initiatives",
            "confirmed technology stack": "confirmed_tech_stack",
            "technology stack": "confirmed_tech_stack",
            "technical hiring signals": "hiring_signals",
            "hiring signals": "hiring_signals",
            "stated business problems": "business_problems",
            "business problems": "business_problems",
            "product fit analysis": "product_fit",
            "fit analysis": "product_fit",
            "recommended talking points": "talking_points",
            "talking points": "talking_points",
            "recent news & press": "recent_news",
            "recent news and press": "recent_news",
            "recent news": "recent_news",
            "key contacts": "key_contacts",
            "contacts": "key_contacts",
            "information gaps": "information_gaps",
        }

        current_section = None
        current_content = []

        for line in markdown.split("\n"):
            if line.startswith("## "):
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                header_text = line[3:].strip().lower()
                # Try exact match first
                current_section = header_mapping.get(header_text)
                # If no exact match, check for partial matches (e.g., "X Fit Analysis")
                if not current_section:
                    if "fit analysis" in header_text:
                        current_section = "product_fit"
                    elif "talking points" in header_text:
                        current_section = "talking_points"
                    elif "information gaps" in header_text:
                        current_section = "information_gaps"
                current_content = []
            else:
                if current_section:
                    current_content.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _extract_domain(self, url: str) -> str:
        """Extract domain name from URL."""
        domain = url.replace("https://", "").replace("http://", "")
        domain = domain.split("/")[0]
        return domain.replace("www.", "")
