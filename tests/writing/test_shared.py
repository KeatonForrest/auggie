"""Tests for shared WritingService functionality: report building, formatting, relevance gate."""

import pytest
from unittest.mock import patch, MagicMock

from services.writing import WritingService
from services.writing.postprocess import extract_company_core


# --- _build_report ---


class TestBuildReport:
    def test_includes_company_name(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "Our product does X.")
        assert "Acme Corp" in report

    def test_includes_product_context(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "MongoDB Atlas")
        assert "MongoDB Atlas" in report

    def test_includes_optional_sections_when_present(self, writing_service, sample_document):
        sample_document.business_problems = "Scaling issues."
        sample_document.confirmed_tech_stack = "React, Node.js"
        report = writing_service._build_report(sample_document, "Product")
        assert "Scaling issues." in report
        # Tech stack intentionally excluded from outreach context
        assert "React, Node.js" not in report

    def test_omits_optional_sections_when_empty(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "Product")
        assert "Business Problems" not in report
        assert "Technology Stack" not in report

    def test_includes_existential_data_points(self, writing_service, sample_document):
        sample_document.existential_data_points = "Series B funding running out"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Existential Data Points (Urgency Signals)" in report
        assert "Series B funding running out" in report

    def test_includes_projects_initiatives(self, writing_service, sample_document):
        sample_document.projects_initiatives = "Launching new AI product line"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Current Projects & Initiatives" in report
        assert "Launching new AI product line" in report

    def test_includes_talking_points(self, writing_service, sample_document):
        sample_document.talking_points = "Focus on scalability and cost reduction"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Recommended Talking Points" in report
        assert "Focus on scalability and cost reduction" in report

    def test_includes_key_contacts(self, writing_service, sample_document):
        sample_document.key_contacts = "John Doe (CTO), Jane Smith (VP Engineering)"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Key Contacts" in report
        assert "John Doe (CTO)" in report

    def test_includes_seller_company(self, writing_service, sample_document):
        report = writing_service._build_report(
            sample_document, "Our product", seller_company="MongoDB Inc"
        )
        assert "**Company:** MongoDB Inc" in report

    def test_includes_problems_solved(self, writing_service, sample_document):
        report = writing_service._build_report(
            sample_document, "Our product",
            problems_solved="Database scalability, Performance optimization"
        )
        assert "## Specific Problems We Solve" in report
        assert "Database scalability, Performance optimization" in report

    def test_includes_retrieved_materials(self, writing_service, sample_document):
        materials = "Case Study: Acme Corp reduced costs by 40%"
        report = writing_service._build_report(
            sample_document, "Our product", retrieved_materials=materials
        )
        assert "## Sales Materials (Case Studies, Battle Cards, Proof Points)" in report
        assert "Acme Corp reduced costs by 40%" in report

    def test_all_optional_fields_together(self, writing_service, full_document):
        report = writing_service._build_report(
            full_document, "MongoDB Atlas",
            retrieved_materials="Case studies here",
            seller_company="MongoDB Inc",
            problems_solved="Scalability, Performance"
        )
        assert "## Existential Data Points" in report
        assert "## Current Projects & Initiatives" in report
        assert "## Technology Stack" not in report
        assert "## Recommended Talking Points" in report
        assert "## Key Contacts" in report
        assert "**Company:** MongoDB Inc" in report
        assert "## Specific Problems We Solve" in report
        assert "## Sales Materials" in report


# --- format_emails_markdown ---


class TestFormatEmailsMarkdown:
    def test_format_single_email(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "Test subject", "body": "This is the email body."}
        ]
        markdown = writing_service.format_emails_markdown(emails)
        assert "# Email Sequence" in markdown
        assert "## Email 1" in markdown
        assert "**Subject:** Test subject" in markdown
        assert "This is the email body." in markdown

    def test_format_multiple_emails(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "Shared subject", "body": "First email body."},
            {"email_number": 2, "subject": "Shared subject", "body": "Second email body."},
            {"email_number": 3, "subject": "Shared subject", "body": "Third email body."},
        ]
        markdown = writing_service.format_emails_markdown(emails)
        assert markdown.count("## Email") == 3
        assert markdown.count("**Subject:**") == 3
        assert markdown.count("---") == 3
        assert "First email body." in markdown
        assert "Second email body." in markdown
        assert "Third email body." in markdown

    def test_format_preserves_email_order(self, writing_service):
        emails = [
            {"email_number": 1, "subject": "Test", "body": "Body 1"},
            {"email_number": 2, "subject": "Test", "body": "Body 2"},
            {"email_number": 3, "subject": "Test", "body": "Body 3"},
        ]
        markdown = writing_service.format_emails_markdown(emails)
        pos1 = markdown.find("Body 1")
        pos2 = markdown.find("Body 2")
        pos3 = markdown.find("Body 3")
        assert pos1 < pos2 < pos3

    def test_format_empty_list(self, writing_service):
        emails = []
        markdown = writing_service.format_emails_markdown(emails)
        assert "# Email Sequence" in markdown


# --- persona_context ---


class TestPersonaContext:
    def test_persona_context_included_in_report(self, writing_service, sample_document):
        report = writing_service._build_report(
            sample_document, "Product",
            persona_context="**Name:** Jane Smith\n**Title:** VP Engineering"
        )
        assert "## Target Contact" in report
        assert "Jane Smith" in report
        assert "VP Engineering" in report

    def test_persona_context_omitted_when_empty(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "Product", persona_context="")
        assert "## Target Contact" not in report

    def test_recommended_contacts_in_report(self, writing_service, sample_document):
        sample_document.recommended_contacts = "VP of Engineering - owns scaling problems"
        report = writing_service._build_report(sample_document, "Product")
        assert "## Recommended Contacts" in report
        assert "VP of Engineering" in report

    def test_recommended_contacts_omitted_when_empty(self, writing_service, sample_document):
        report = writing_service._build_report(sample_document, "Product")
        assert "## Recommended Contacts" not in report


# --- Tight writing regression ---


class TestTightWritingRegression:
    def test_tightened_content_includes_all_action_fields(self, writing_service, sample_document):
        sample_document.business_problems = "- Scaling is hard."
        sample_document.existential_data_points = "- DB at 90% capacity."
        sample_document.before_scenario = "Problems: scaling. Consequences: outages."
        sample_document.pvp_seed = "Key insight in 60 words."
        sample_document.talking_points = "- Hook 1\n- Hook 2"
        sample_document.product_fit = "High fit."

        report = writing_service._build_report(sample_document, "Our product")

        assert "## Business Problems" in report
        assert "## Existential Data Points" in report
        assert "## Before Scenario" in report
        assert "## PVP Seed" in report
        assert "## Recommended Talking Points" in report
        assert "## Product Fit Analysis" in report

    def test_empty_sections_gracefully_omitted(self, writing_service, sample_document):
        sample_document.business_problems = ""
        sample_document.existential_data_points = ""
        sample_document.before_scenario = ""
        sample_document.pvp_seed = ""
        sample_document.talking_points = ""

        report = writing_service._build_report(sample_document, "Our product")

        assert "## Business Problems" not in report
        assert "## Existential Data Points" not in report
        assert "## Before Scenario" not in report
        assert "## PVP Seed" not in report
        assert "## Recommended Talking Points" not in report
        assert "## Company Overview" in report


# --- Product-relevance gate ---


class TestCategoryDetection:
    def test_detects_database_from_multi_keyword_context(self, writing_service):
        ctx = "MongoDB Atlas - scalable database platform for modern applications"
        assert writing_service._detect_product_category(ctx) == "database"

    def test_returns_empty_for_unrelated_product(self, writing_service):
        ctx = "Salesforce CRM for enterprise sales teams"
        assert writing_service._detect_product_category(ctx) == ""

    def test_returns_empty_for_empty_input(self, writing_service):
        assert writing_service._detect_product_category("") == ""


class TestHookRelevanceScoring:
    def test_clean_hook_scores_5(self, writing_service):
        text = "- Their data pipeline is growing 3x year-over-year"
        assert writing_service._score_hook_relevance(text, "database") == 5

    def test_blocked_with_linkage_scores_4(self, writing_service):
        text = "- React frontend rebuild causing database bottleneck in API layer"
        assert writing_service._score_hook_relevance(text, "database") == 4

    def test_blocked_without_linkage_scores_2(self, writing_service):
        text = "- They recently migrated their frontend to React and Vue"
        assert writing_service._score_hook_relevance(text, "database") == 2

    def test_unknown_category_scores_5(self, writing_service):
        text = "- CDN migration underway with Cloudflare"
        assert writing_service._score_hook_relevance(text, "unknown_cat") == 5


class TestRelevanceGate:
    def _make_report(self, talking_points: str) -> str:
        return (
            "## Company Overview\nAcme Corp builds software.\n\n"
            "## Business Problems & Pain Points\nScaling issues.\n\n"
            "## Recommended Talking Points\n" + talking_points + "\n\n"
            "## Product Fit Analysis\nGood fit."
        )

    def test_cdn_hook_removed_db_hook_kept(self, writing_service):
        tp = (
            "- Their Cloudflare CDN setup is expanding rapidly\n"
            "- Database query latency is growing with user count"
        )
        report = self._make_report(tp)
        result = writing_service._apply_relevance_gate(report, "database")
        assert "Database query latency" in result
        assert "Cloudflare CDN" not in result

    def test_cdn_with_db_linkage_kept(self, writing_service):
        tp = "- Cloudflare CDN changes causing database bottleneck in API"
        report = self._make_report(tp)
        result = writing_service._apply_relevance_gate(report, "database")
        assert "database bottleneck" in result

    def test_all_hooks_filtered_appends_fallback(self, writing_service):
        tp = (
            "- React frontend rewrite underway\n"
            "- Tailwind CSS adoption across all products"
        )
        report = self._make_report(tp)
        result = writing_service._apply_relevance_gate(report, "database")
        assert "React frontend" not in result
        assert "Tailwind CSS" not in result
        assert "Fallback:" in result
        assert "Business Problems" in result

    def test_non_talking_points_sections_untouched(self, writing_service):
        tp = "- React frontend rewrite"
        report = self._make_report(tp)
        result = writing_service._apply_relevance_gate(report, "database")
        assert "## Company Overview\nAcme Corp builds software." in result
        assert "## Product Fit Analysis\nGood fit." in result

    def test_unknown_category_returns_unchanged(self, writing_service):
        tp = "- React frontend rewrite"
        report = self._make_report(tp)
        result = writing_service._apply_relevance_gate(report, "unknown_cat")
        assert result == report


class TestExtractCompanyCore:
    def test_strips_inc(self):
        assert extract_company_core("MongoDB, Inc.") == "mongodb"

    def test_strips_dotcom(self):
        assert extract_company_core("nike.com") == "nike"

    def test_strips_corp(self):
        assert extract_company_core("Acme Corp") == "acme"

    def test_strips_llc(self):
        assert extract_company_core("DataCo LLC") == "dataco"

    def test_plain_name_unchanged(self):
        assert extract_company_core("Fortive") == "fortive"

    def test_short_name_returns_original(self):
        assert extract_company_core("AI") == "ai"
