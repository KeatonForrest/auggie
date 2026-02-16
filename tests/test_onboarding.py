"""Tests for onboarding-related logic: normalization, product context, motion."""

import pytest

from routes._helpers import normalize_industries, BUYER_CATEGORIES, _LEGACY_INDUSTRY_MAP
from db.users import build_product_context


class TestNormalizeIndustries:
    """Tests for legacy → new category mapping."""

    def test_new_categories_pass_through(self):
        """Values already in new taxonomy are unchanged."""
        cats = ["Fintech", "HealthTech", "Cybersecurity"]
        assert normalize_industries(cats) == cats

    def test_legacy_labels_mapped(self):
        """Old industry labels are mapped to new categories."""
        legacy = ["Healthcare / Life Sciences", "Insurance", "Construction"]
        result = normalize_industries(legacy)
        assert result == ["HealthTech", "InsurTech", "ConstructionTech"]

    def test_saas_software_maps_to_horizontal(self):
        """'SaaS / Software' maps to 'Horizontal / Cross-industry', not 'DevTools / Infra'."""
        result = normalize_industries(["SaaS / Software"])
        assert result == ["Horizontal / Cross-industry"]

    def test_deduplication(self):
        """Multiple legacy labels mapping to the same category are deduped."""
        # Manufacturing, Professional Services, Energy / Utilities, SaaS / Software all → Horizontal / Cross-industry
        legacy = ["Manufacturing", "Professional Services", "Energy / Utilities"]
        result = normalize_industries(legacy)
        assert result == ["Horizontal / Cross-industry"]

    def test_mixed_legacy_and_new(self):
        """Mix of legacy and new-taxonomy values normalizes correctly."""
        mixed = ["Fintech / Financial Services", "Cybersecurity", "EdTech"]
        result = normalize_industries(mixed)
        assert result == ["Fintech", "Cybersecurity", "EdTech"]

    def test_unknown_labels_preserved(self):
        """Unrecognized labels pass through as-is."""
        result = normalize_industries(["Fintech", "Alien Tech"])
        assert result == ["Fintech", "Alien Tech"]

    def test_empty_input(self):
        """Empty list returns empty."""
        assert normalize_industries([]) == []

    def test_all_legacy_labels_have_mappings(self):
        """Every key in the legacy map maps to a valid new category."""
        for legacy, new in _LEGACY_INDUSTRY_MAP.items():
            assert new in BUYER_CATEGORIES, f"{legacy} maps to {new} which is not in BUYER_CATEGORIES"

    def test_category_count(self):
        """Exactly 17 buyer product categories."""
        assert len(BUYER_CATEGORIES) == 17


class TestBuildProductContext:
    """Tests for build_product_context labels."""

    def test_solution_motion_horizontal(self):
        """solution_motion='horizontal' produces Horizontal motion label."""
        ctx = build_product_context(
            product_name="Acme DB",
            product_description="Database tool",
            problems_solved="Slow queries",
            differentiators="Fast indexing",
            target_company_size="Mid-market",
            target_industries="Fintech, HealthTech",
            target_personas="CTO",
            competitors="Oracle",
            solution_motion="horizontal",
        )
        assert "**Solution motion:** Horizontal" in ctx

    def test_solution_motion_vertical(self):
        """solution_motion='vertical' produces Vertical motion label."""
        ctx = build_product_context(
            product_name="MSP Co",
            product_description="IT services",
            problems_solved="No IT staff",
            differentiators="24/7 support",
            target_company_size="SMB",
            target_industries="HealthTech",
            target_personas="Office Manager",
            competitors="Local MSP",
            solution_motion="vertical",
        )
        assert "**Solution motion:** Vertical" in ctx

    def test_motion_independent_of_product_type(self):
        """product_type='saas' + solution_motion='vertical' produces Vertical label."""
        ctx = build_product_context(
            product_name="HealthSaaS",
            product_description="Healthcare compliance tool",
            problems_solved="HIPAA compliance gaps",
            differentiators="",
            target_company_size="",
            target_industries="HealthTech",
            target_personas="",
            competitors="",
            product_type="saas",
            solution_motion="vertical",
        )
        assert "**Solution motion:** Vertical" in ctx

    def test_msp_horizontal_produces_horizontal(self):
        """product_type='msp' + solution_motion='horizontal' produces Horizontal label."""
        ctx = build_product_context(
            product_name="IT Everywhere",
            product_description="Managed IT",
            problems_solved="No IT staff",
            differentiators="",
            target_company_size="",
            target_industries="",
            target_personas="",
            competitors="",
            product_type="msp",
            solution_motion="horizontal",
        )
        assert "**Solution motion:** Horizontal" in ctx

    def test_buyer_categories_label(self):
        """Industries are labeled as 'Buyer product categories'."""
        ctx = build_product_context(
            product_name="",
            product_description="",
            problems_solved="Problems",
            differentiators="",
            target_company_size="",
            target_industries="Fintech, Cybersecurity",
            target_personas="",
            competitors="",
        )
        assert "**Buyer product categories:** Fintech, Cybersecurity" in ctx

    def test_empty_fields_omitted(self):
        """Empty optional fields are not included in output."""
        ctx = build_product_context(
            product_name="",
            product_description="",
            problems_solved="Core pain",
            differentiators="",
            target_company_size="",
            target_industries="",
            target_personas="",
            competitors="",
        )
        assert "**Problems it solves:** Core pain" in ctx
        assert "**Product:**" not in ctx
        assert "**Buyer product categories:**" not in ctx
        assert "**Solution motion:** Horizontal" in ctx  # default

    def test_default_motion_is_horizontal(self):
        """Omitting solution_motion defaults to Horizontal."""
        ctx = build_product_context(
            product_name="",
            product_description="",
            problems_solved="Pain",
            differentiators="",
            target_company_size="",
            target_industries="",
            target_personas="",
            competitors="",
        )
        assert "**Solution motion:** Horizontal" in ctx
