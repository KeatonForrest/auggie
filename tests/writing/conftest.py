"""Shared fixtures for writing service tests."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from models import ResearchDocument
from services.writing import WritingService
from services.writing.email import EmailStrategy
from services.writing.linkedin_dm import LinkedInDMStrategy
from services.writing.linkedin_connection import LinkedInConnectionStrategy


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
