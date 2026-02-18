"""
conftest.py - Shared test fixtures

Fixtures are reusable test components that pytest injects into tests.
We mock external services here so tests run fast without API calls.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from models import ScrapedContent, ResearchDocument, TechStack, DetectedTechnology
from services.writing import WritingService
from services.writing.email import EmailStrategy
from services.writing.linkedin_dm import LinkedInDMStrategy
from services.writing.linkedin_connection import LinkedInConnectionStrategy


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
    """Fake tech stack that would come from tech detection."""
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
    with patch("routes.research.firecrawl_service") as mock_firecrawl, \
         patch("routes.research.tech_detection_service") as mock_tech_detection, \
         patch("routes.research.claude_service") as mock_claude:

        # Configure mock return values
        mock_firecrawl.scrape_company = AsyncMock(return_value=sample_scraped_content)
        mock_tech_detection.analyze_multiple_domains = AsyncMock(return_value=sample_tech_stack)
        mock_claude.generate_research_document = AsyncMock(return_value=sample_research_document)

        yield {
            "firecrawl": mock_firecrawl,
            "tech_detection": mock_tech_detection,
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


# --- Writing service fixtures (also in tests/writing/conftest.py) ---
# Duplicated here so tests re-exported by tests/test_writing.py can find them.


@pytest.fixture
def writing_service():
    """WritingService with mocked API client."""
    with patch("services.writing.service.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="test-key",
            writing_model="mistralai/mistral-medium-3.1",
            writing_model_email="",
            writing_model_linkedin_dm="",
            writing_model_linkedin_connection="",
            pea_selector_enabled=True,
            writing_relevance_gate_enabled=False,
        )
        with patch("services.writing.service.AsyncOpenAI"):
            service = WritingService()
    return service


@pytest.fixture
def relevance_gate_service():
    """WritingService with relevance gate enabled."""
    with patch("services.writing.service.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="test-key",
            writing_model="mistralai/mistral-medium-3.1",
            writing_model_email="",
            writing_model_linkedin_dm="",
            writing_model_linkedin_connection="",
            pea_selector_enabled=True,
            writing_relevance_gate_enabled=True,
        )
        with patch("services.writing.service.AsyncOpenAI"):
            service = WritingService()
    return service


@pytest.fixture
def sample_document():
    """Minimal research document for prompt tests."""
    return ResearchDocument(
        id=1,
        company_url="https://acme.com",
        company_name="Acme Corp",
        created_at=datetime.now(timezone.utc),
        company_overview="Acme Corp builds enterprise software.",
        projects_initiatives="",
        confirmed_tech_stack="",
        hiring_signals="",
        business_problems="",
        product_fit="Good fit for their data needs.",
        talking_points="",
        information_gaps="",
        full_markdown="",
    )


@pytest.fixture
def full_document():
    """Document with all optional fields populated."""
    return ResearchDocument(
        id=1,
        company_url="https://acme.com",
        company_name="Acme Corp",
        created_at=datetime.now(timezone.utc),
        company_overview="Acme Corp builds enterprise software.",
        projects_initiatives="Launching new AI product line",
        confirmed_tech_stack="React, Node.js, MongoDB",
        hiring_signals="Hiring 5 engineers",
        business_problems="Scaling database performance issues",
        existential_data_points="Series B funding running out in 6 months",
        product_fit="Good fit for their data needs.",
        talking_points="Focus on scalability and cost reduction",
        key_contacts="John Doe (CTO), Jane Smith (VP Engineering)",
        information_gaps="",
        full_markdown="",
        opportunity_score=75,
    )


@pytest.fixture
def email_strategy():
    """Bare EmailStrategy instance (pure logic, no mocks)."""
    return EmailStrategy()


@pytest.fixture
def linkedin_dm_strategy():
    """Bare LinkedInDMStrategy instance (pure logic, no mocks)."""
    return LinkedInDMStrategy()


@pytest.fixture
def linkedin_cr_strategy():
    """Bare LinkedInConnectionStrategy instance (pure logic, no mocks)."""
    return LinkedInConnectionStrategy()
