"""
conftest.py - Shared test fixtures

Fixtures are reusable test components that pytest injects into tests.
We mock external services here so tests run fast without API calls.
"""

import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from models import ScrapedContent, ResearchDocument, TechStack, DetectedTechnology


@pytest.fixture
def sample_scraped_content():
    """Fake scraped content that would come from Firecrawl."""
    return ScrapedContent(
        homepage="# Acme Corp\nWe build amazing software for enterprises.",
        homepage_html="<html><head></head><body>Acme Corp</body></html>",
        about="Acme Corp was founded in 2020. We have 500 employees.",
        careers="We're hiring! Looking for Senior Engineers and Data Scientists.",
        blog="Our latest post: How we scaled to 1 million users.",
        job_postings="Senior Backend Engineer - Python, PostgreSQL, Redis required.",
        additional_pages="Our product helps teams collaborate better.",
        news="Acme Corp raises $50M Series B.",
    )


@pytest.fixture
def sample_tech_stack():
    """Fake tech stack that would come from Wappalyzer."""
    return {
        "acme.com": TechStack(
            technologies=[
                DetectedTechnology(name="React", category="JavaScript frameworks"),
                DetectedTechnology(name="Node.js", category="Web servers"),
                DetectedTechnology(name="PostgreSQL", category="Databases"),
            ],
            scan_url="https://acme.com"
        ),
        "app.acme.com": TechStack(
            technologies=[
                DetectedTechnology(name="React", category="JavaScript frameworks"),
                DetectedTechnology(name="Redux", category="JavaScript frameworks"),
                DetectedTechnology(name="GraphQL", category="Miscellaneous"),
            ],
            scan_url="https://app.acme.com"
        ),
    }


@pytest.fixture
def sample_research_document():
    """Fake research document that would come from Claude."""
    return ResearchDocument(
        id=1,
        company_url="https://acme.com",
        company_name="acme.com",
        created_at=datetime.now(),
        company_overview="Acme Corp is an enterprise software company.",
        projects_initiatives="Building a new data platform.",
        confirmed_tech_stack="React, Node.js, PostgreSQL detected.",
        hiring_signals="Hiring for backend and data roles.",
        business_problems="Scaling challenges mentioned in blog.",
        product_fit="HIGH - Their PostgreSQL usage could benefit from MongoDB.",
        talking_points="1. Discuss their scaling challenges.\n2. MongoDB Atlas.",
        information_gaps="No pricing page found.",
        full_markdown="# Acme Corp Research\n\n## Company Overview\nAcme Corp is...",
    )


@pytest.fixture
def mock_services(sample_scraped_content, sample_tech_stack, sample_research_document):
    """Mock all three services at once."""
    with patch("main.firecrawl_service") as mock_firecrawl, \
         patch("main.wappalyzer_service") as mock_wappalyzer, \
         patch("main.claude_service") as mock_claude:

        # Configure mock return values
        mock_firecrawl.scrape_company = AsyncMock(return_value=sample_scraped_content)
        mock_wappalyzer.analyze_multiple_domains = AsyncMock(return_value=sample_tech_stack)
        mock_claude.generate_research_document = AsyncMock(return_value=sample_research_document)

        yield {
            "firecrawl": mock_firecrawl,
            "wappalyzer": mock_wappalyzer,
            "claude": mock_claude,
        }


@pytest.fixture
def fake_user():
    """Fake authenticated user for route tests."""
    return {
        "id": 1,
        "email": "test@test.com",
        "name": "Test User",
        "product_context": "Test product context",
        "company_name": "Test Co",
    }


@pytest_asyncio.fixture
async def async_client():
    """Async HTTP client for testing FastAPI endpoints (unauthenticated)."""
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def authed_client(fake_user):
    """Async HTTP client with authentication mocked."""
    from main import app

    with patch("auth.get_current_user", new_callable=AsyncMock, return_value=fake_user):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
