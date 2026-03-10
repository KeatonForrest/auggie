"""Tests for category normalization and role relevance mapping."""

import pytest

from services.writing.types import (
    CATEGORY_SLUG_MAP,
    SELLER_RELEVANT_ROLES,
    normalize_seller_category,
)


class TestNormalizeSellerCategory:
    @pytest.mark.parametrize("ui_string,expected_slug", list(CATEGORY_SLUG_MAP.items()))
    def test_all_ui_strings(self, ui_string, expected_slug):
        assert normalize_seller_category(ui_string) == expected_slug

    def test_legacy_cybersecurity_alias(self):
        assert normalize_seller_category("Cybersecurity") == "cybersecurity"

    def test_empty_returns_empty(self):
        assert normalize_seller_category("") == ""

    def test_none_returns_empty(self):
        assert normalize_seller_category(None) == ""

    def test_unknown_returns_empty(self):
        assert normalize_seller_category("UnknownCategory") == ""

    def test_other_returns_empty(self):
        assert normalize_seller_category("Other / Cross-industry") == ""


class TestCategorySlugMap:
    def test_has_17_entries(self):
        assert len(CATEGORY_SLUG_MAP) == 17

    def test_all_expected_ui_strings_present(self):
        # These must match the <option value="..."> strings in
        # templates/onboarding.html and templates/settings.html.
        expected = {
            "MarTech", "Fintech", "HealthTech", "ConstructionTech", "EdTech",
            "PropTech", "InsurTech", "LegalTech", "HRTech", "Cybersecurity / IT",
            "DevTools / Infra", "E-commerce Tech",
            "Supply Chain / Logistics Tech", "GovTech", "TravelTech",
            "MediaTech", "Other / Cross-industry",
        }
        assert set(CATEGORY_SLUG_MAP.keys()) == expected


class TestSellerRelevantRoles:
    def test_all_non_empty_slugs_have_roles(self):
        """Every slug in CATEGORY_SLUG_MAP (except '') should have a SELLER_RELEVANT_ROLES entry."""
        slugs = {v for v in CATEGORY_SLUG_MAP.values() if v}
        for slug in slugs:
            assert slug in SELLER_RELEVANT_ROLES, f"Missing SELLER_RELEVANT_ROLES for {slug}"

    def test_no_extra_slugs(self):
        """SELLER_RELEVANT_ROLES should not have slugs absent from CATEGORY_SLUG_MAP."""
        valid_slugs = {v for v in CATEGORY_SLUG_MAP.values() if v}
        for slug in SELLER_RELEVANT_ROLES:
            assert slug in valid_slugs, f"Unexpected slug in SELLER_RELEVANT_ROLES: {slug}"

    def test_martech_roles(self):
        assert SELLER_RELEVANT_ROLES["martech"] == {"marketing", "sales", "product", "data"}

    def test_devtools_roles(self):
        assert SELLER_RELEVANT_ROLES["devtools"] == {"devops", "backend", "fullstack", "data", "frontend"}

    def test_constructiontech_includes_project_management(self):
        assert "project_management" in SELLER_RELEVANT_ROLES["constructiontech"]


class TestSlugMapMatchesTemplates:
    """Guard against CATEGORY_SLUG_MAP keys drifting from the persisted form values."""

    def test_fintech_exact_casing(self):
        assert "Fintech" in CATEGORY_SLUG_MAP  # not "FinTech"

    def test_ecommerce_exact_label(self):
        assert "E-commerce Tech" in CATEGORY_SLUG_MAP  # not "E-commerce / Retail Tech"

    def test_mediatech_exact_label(self):
        assert "MediaTech" in CATEGORY_SLUG_MAP  # not "Media / Entertainment Tech"
