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
