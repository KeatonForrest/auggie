"""Tests for onboarding-related logic: normalization, product context, seller/buyer split."""

import pytest

from routes._helpers import (
    normalize_verticals, SELLER_PRODUCT_CATEGORIES, BUYER_VERTICALS,
    _LEGACY_VERTICAL_MAP,
)
from db.users import build_product_context


class TestNormalizeVerticals:
    """Tests for legacy → buyer-vertical mapping."""

    def test_buyer_verticals_pass_through(self):
        """Values already in BUYER_VERTICALS are unchanged."""
        verts = ["Financial Services", "Healthcare", "Construction"]
        assert normalize_verticals(verts) == verts

    def test_v1_legacy_labels_mapped(self):
        """Original v1 industry labels map to buyer verticals."""
        legacy = ["Fintech / Financial Services", "Healthcare / Life Sciences", "E-commerce / Retail"]
        result = normalize_verticals(legacy)
        assert result == ["Financial Services", "Healthcare", "Retail / E-commerce"]

    def test_v2_tech_category_labels_mapped(self):
        """Brief v2 tech-category labels (stored in target_industries) map to verticals."""
        tech_cats = ["Fintech", "HealthTech", "InsurTech", "ConstructionTech"]
        result = normalize_verticals(tech_cats)
        assert result == ["Financial Services", "Healthcare", "Insurance", "Construction"]

    def test_deduplication(self):
        """Multiple labels mapping to the same vertical are deduped."""
        # "SaaS / Software", "Cybersecurity", "DevTools / Infra" all → Technology
        labels = ["SaaS / Software", "Cybersecurity", "DevTools / Infra"]
        result = normalize_verticals(labels)
        assert result == ["Technology"]

    def test_mixed_legacy_and_current(self):
        """Mix of legacy, tech-category, and current labels normalizes correctly."""
        mixed = ["Fintech / Financial Services", "EdTech", "Healthcare"]
        result = normalize_verticals(mixed)
        assert result == ["Financial Services", "Education", "Healthcare"]

    def test_unknown_labels_preserved(self):
        """Unrecognized labels pass through as-is."""
        result = normalize_verticals(["Healthcare", "Alien Industry"])
        assert result == ["Healthcare", "Alien Industry"]

    def test_empty_input(self):
        """Empty list returns empty."""
        assert normalize_verticals([]) == []

    def test_all_legacy_map_values_are_valid_verticals(self):
        """Every value in the legacy map is a valid buyer vertical."""
        for legacy, vertical in _LEGACY_VERTICAL_MAP.items():
            assert vertical in BUYER_VERTICALS, f"{legacy} maps to {vertical} which is not in BUYER_VERTICALS"

    def test_buyer_vertical_count(self):
        """Exactly 17 buyer company verticals."""
        assert len(BUYER_VERTICALS) == 17

    def test_seller_category_count(self):
        """Exactly 17 seller product categories."""
        assert len(SELLER_PRODUCT_CATEGORIES) == 17


class TestBuildProductContext:
    """Tests for build_product_context output."""

    def test_seller_product_category_included(self):
        """seller_product_category appears as its own labeled line."""
        ctx = build_product_context(
            product_name="Acme Compliance",
            product_description="",
            problems_solved="HIPAA gaps",
            differentiators="",
            target_company_size="",
            target_industries="Healthcare",
            target_personas="",
            competitors="",
            seller_product_category="HealthTech",
        )
        assert "**Seller product category:** HealthTech" in ctx

    def test_buyer_verticals_label(self):
        """target_industries renders as 'Buyer company verticals'."""
        ctx = build_product_context(
            product_name="",
            product_description="",
            problems_solved="Pain",
            differentiators="",
            target_company_size="",
            target_industries="Financial Services, Healthcare",
            target_personas="",
            competitors="",
        )
        assert "**Buyer company verticals:** Financial Services, Healthcare" in ctx

    def test_solution_motion_horizontal(self):
        """solution_motion='horizontal' produces Horizontal label."""
        ctx = build_product_context(
            product_name="",
            product_description="",
            problems_solved="Pain",
            differentiators="",
            target_company_size="",
            target_industries="",
            target_personas="",
            competitors="",
            solution_motion="horizontal",
        )
        assert "**Solution motion:** Horizontal" in ctx

    def test_solution_motion_vertical(self):
        """solution_motion='vertical' produces Vertical label."""
        ctx = build_product_context(
            product_name="",
            product_description="",
            problems_solved="Pain",
            differentiators="",
            target_company_size="",
            target_industries="",
            target_personas="",
            competitors="",
            solution_motion="vertical",
        )
        assert "**Solution motion:** Vertical" in ctx

    def test_motion_independent_of_product_type(self):
        """product_type='saas' + solution_motion='vertical' = Vertical."""
        ctx = build_product_context(
            product_name="",
            product_description="",
            problems_solved="Pain",
            differentiators="",
            target_company_size="",
            target_industries="",
            target_personas="",
            competitors="",
            product_type="saas",
            solution_motion="vertical",
        )
        assert "**Solution motion:** Vertical" in ctx

    def test_empty_seller_category_omitted(self):
        """Empty seller_product_category is not included in output."""
        ctx = build_product_context(
            product_name="",
            product_description="",
            problems_solved="Pain",
            differentiators="",
            target_company_size="",
            target_industries="",
            target_personas="",
            competitors="",
            seller_product_category="",
        )
        assert "**Seller product category:**" not in ctx

    def test_empty_verticals_omitted(self):
        """Empty target_industries is not included in output."""
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
        assert "**Buyer company verticals:**" not in ctx

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
