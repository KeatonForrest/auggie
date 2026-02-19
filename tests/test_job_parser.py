"""Tests for services/job_parser.py"""

import pytest
from services.job_parser import JobParser


@pytest.fixture
def parser():
    return JobParser()


class TestJobParser:
    def test_tech_extraction(self, parser):
        text = "We use Python, React, PostgreSQL, and AWS for our stack."
        result = parser.parse(text)
        names = [tm.name for tm in result.tech_mentions]
        assert "Python" in names
        assert "React" in names
        assert "PostgreSQL" in names
        assert "AWS" in names

    def test_role_types(self, parser):
        text = "Hiring: Senior Backend Engineer, Frontend Developer, Data Scientist"
        result = parser.parse(text)
        assert "backend" in result.role_types
        assert "frontend" in result.role_types
        assert "data" in result.role_types

    def test_seniority(self, parser):
        text = "Senior Engineer x3, Junior Developer x1, Staff Engineer x2"
        result = parser.parse(text)
        assert "senior" in result.seniority_distribution
        assert "junior" in result.seniority_distribution
        assert "staff" in result.seniority_distribution

    def test_empty_input(self, parser):
        result = parser.parse("")
        assert result.tech_mentions == []
        assert result.role_types == []
        assert result.seniority_distribution == {}
        assert result.total_roles_parsed == 0

    def test_none_input(self, parser):
        result = parser.parse(None)
        assert result.tech_mentions == []

    def test_categories(self, parser):
        text = "Experience with Docker, Kubernetes, Terraform required."
        result = parser.parse(text)
        cats = {tm.category for tm in result.tech_mentions}
        assert "devops" in cats

    def test_count(self, parser):
        text = "Python Python Python and Java"
        result = parser.parse(text)
        python = [tm for tm in result.tech_mentions if tm.name == "Python"][0]
        assert python.count == 3

    def test_devops_role(self, parser):
        text = "Looking for a DevOps engineer and SRE to join us."
        result = parser.parse(text)
        assert "devops" in result.role_types

    def test_mobile_role(self, parser):
        text = "iOS engineer needed for mobile development"
        result = parser.parse(text)
        assert "mobile" in result.role_types

    # --- Business-function role tests ---

    def test_marketing_role(self, parser):
        text = "We're hiring a Marketing Manager to lead demand generation."
        result = parser.parse(text)
        assert "marketing" in result.role_types

    def test_marketing_growth(self, parser):
        text = "Growth marketing lead needed to scale acquisition."
        result = parser.parse(text)
        assert "marketing" in result.role_types

    def test_sales_role(self, parser):
        text = "Looking for an Account Executive and Sales Manager."
        result = parser.parse(text)
        assert "sales" in result.role_types

    def test_finance_role(self, parser):
        text = "Hiring a Financial Analyst and Finance Manager."
        result = parser.parse(text)
        assert "finance" in result.role_types

    def test_operations_role(self, parser):
        text = "Operations Manager needed for supply chain optimization."
        result = parser.parse(text)
        assert "operations" in result.role_types

    def test_healthcare_clinical_role(self, parser):
        text = "Clinical Director to oversee patient care programs."
        result = parser.parse(text)
        assert "healthcare_clinical" in result.role_types

    def test_hr_people_role(self, parser):
        text = "HR Manager and Talent Acquisition specialist opening."
        result = parser.parse(text)
        assert "hr_people" in result.role_types

    def test_legal_compliance_role(self, parser):
        text = "Compliance Officer for regulatory affairs and risk."
        result = parser.parse(text)
        assert "legal_compliance" in result.role_types

    def test_product_role(self, parser):
        text = "Product Manager and UX Designer for our platform team."
        result = parser.parse(text)
        assert "product" in result.role_types

    def test_project_management_role(self, parser):
        text = "Project Manager needed for cross-functional initiatives."
        result = parser.parse(text)
        assert "project_management" in result.role_types
        assert "construction" not in result.role_types

    def test_construction_role(self, parser):
        text = "Estimator and Superintendent for field operations."
        result = parser.parse(text)
        assert "construction" in result.role_types

    def test_education_role(self, parser):
        text = "Curriculum Designer and Instructional Designer wanted."
        result = parser.parse(text)
        assert "education" in result.role_types

    # --- False-positive guards ---

    def test_bare_marketing_no_match(self, parser):
        """Bare 'marketing' in company description should NOT trigger marketing role."""
        text = "Our marketing platform helps companies reach customers through digital advertising."
        result = parser.parse(text)
        assert "marketing" not in result.role_types

    def test_bare_operations_no_match(self, parser):
        """Bare 'operations' in company description should NOT trigger operations role."""
        text = "We streamline operations for mid-market companies."
        result = parser.parse(text)
        assert "operations" not in result.role_types

    # --- Mixed role detection ---

    def test_mixed_tech_and_business_roles(self, parser):
        text = (
            "Hiring: Senior Backend Engineer, Marketing Manager, "
            "Data Scientist, Product Manager, Operations Manager"
        )
        result = parser.parse(text)
        assert "backend" in result.role_types
        assert "marketing" in result.role_types
        assert "data" in result.role_types
        assert "product" in result.role_types
        assert "operations" in result.role_types

    def test_total_roles_parsed_counts_business_titles(self, parser):
        text = "\nMarketing Manager\nSales Director\nOperations Analyst\n"
        result = parser.parse(text)
        assert result.total_roles_parsed >= 3
