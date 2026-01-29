"""
test_services.py - Unit tests for services

Tests for individual service functions, particularly parsing
and formatting logic that doesn't require API calls.
"""

import pytest
from models import TechStack, DetectedTechnology, format_multi_domain_tech


class TestTechStackFormatting:
    """Tests for technology stack formatting."""

    def test_format_single_domain(self):
        """Single domain tech stack formats correctly."""
        tech_by_domain = {
            "acme.com": TechStack(
                technologies=[
                    DetectedTechnology(name="React", category="JavaScript frameworks"),
                    DetectedTechnology(name="Node.js", version="18.0", category="Web servers"),
                ],
                scan_url="https://acme.com"
            )
        }

        result = format_multi_domain_tech(tech_by_domain)

        assert "acme.com" in result
        assert "React" in result
        assert "Node.js 18.0" in result
        assert "Marketing Site" in result  # Default domain type

    def test_format_app_subdomain(self):
        """App subdomains are labeled as Product/Application."""
        tech_by_domain = {
            "app.acme.com": TechStack(
                technologies=[
                    DetectedTechnology(name="Vue.js", category="JavaScript frameworks"),
                ],
                scan_url="https://app.acme.com"
            )
        }

        result = format_multi_domain_tech(tech_by_domain)

        assert "app.acme.com" in result
        assert "Product/Application" in result

    def test_format_empty_tech_stack(self):
        """Empty tech stack returns appropriate message."""
        result = format_multi_domain_tech({})
        assert result == "No technologies detected."

    def test_format_multiple_domains(self):
        """Multiple domains format with separation."""
        tech_by_domain = {
            "acme.com": TechStack(
                technologies=[DetectedTechnology(name="WordPress")],
                scan_url="https://acme.com"
            ),
            "app.acme.com": TechStack(
                technologies=[DetectedTechnology(name="React")],
                scan_url="https://app.acme.com"
            ),
        }

        result = format_multi_domain_tech(tech_by_domain)

        assert "acme.com" in result
        assert "app.acme.com" in result
        assert "WordPress" in result
        assert "React" in result


class TestTechStackModel:
    """Tests for TechStack model methods."""

    def test_to_prompt_text_with_technologies(self):
        """TechStack formats technologies for prompts."""
        tech_stack = TechStack(
            technologies=[
                DetectedTechnology(name="Python", version="3.10", category="Programming languages"),
                DetectedTechnology(name="FastAPI", category="Web frameworks"),
            ]
        )

        result = tech_stack.to_prompt_text()

        assert "- Python 3.10 (Programming languages)" in result
        assert "- FastAPI (Web frameworks)" in result

    def test_to_prompt_text_empty(self):
        """Empty TechStack returns appropriate message."""
        tech_stack = TechStack(technologies=[])

        result = tech_stack.to_prompt_text()

        assert result == "No technologies detected."

    def test_to_prompt_text_no_version(self):
        """Technologies without version format correctly."""
        tech_stack = TechStack(
            technologies=[
                DetectedTechnology(name="Redis"),
            ]
        )

        result = tech_stack.to_prompt_text()

        assert "- Redis" in result
        assert "None" not in result


class TestClaudeSectionParsing:
    """Tests for Claude response parsing logic."""

    def test_parse_standard_sections(self):
        """Standard markdown sections are parsed correctly."""
        from services.claude import ClaudeService

        service = ClaudeService.__new__(ClaudeService)  # Create without __init__

        markdown = """## Company Overview
Acme Corp builds enterprise software.

## Specific Projects & Initiatives
Building a data platform.

## Confirmed Technology Stack
React, Node.js, PostgreSQL

## Technical Hiring Signals
Hiring backend engineers.

## Stated Business Problems
Scaling issues mentioned.

## Product Fit Analysis
HIGH - Good fit for their needs.

## Recommended Talking Points
1. Discuss scaling
2. Show Atlas demo

## Information Gaps
No pricing info found.
"""

        sections = service._parse_sections(markdown)

        assert "company_overview" in sections
        assert "Acme Corp" in sections["company_overview"]
        assert "projects_initiatives" in sections
        assert "confirmed_tech_stack" in sections
        assert "hiring_signals" in sections
        assert "business_problems" in sections
        assert "product_fit" in sections
        assert "talking_points" in sections
        assert "information_gaps" in sections

    def test_parse_handles_missing_sections(self):
        """Missing sections don't crash the parser."""
        from services.claude import ClaudeService

        service = ClaudeService.__new__(ClaudeService)

        markdown = """## Company Overview
Just this section.
"""

        sections = service._parse_sections(markdown)

        assert "company_overview" in sections
        assert "projects_initiatives" not in sections  # Missing is okay
