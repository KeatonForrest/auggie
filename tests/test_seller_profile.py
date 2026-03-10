"""Tests for seller website profile enrichment."""

from unittest.mock import MagicMock, patch

import pytest

from services.seller_profile import SellerProfileService


@pytest.fixture
def service():
    with patch("services.seller_profile.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            openrouter_api_key="",
            research_model="google/gemini-2.5-flash",
        )
        yield SellerProfileService(firecrawl_service=MagicMock())


def test_select_profile_urls_prefers_high_signal_pages(service):
    urls = [
        "https://acme.com/blog/launch",
        "https://acme.com/product",
        "https://acme.com/solutions/revenue-operations",
        "https://acme.com/customers",
        "https://acme.com/privacy",
    ]

    selected = service.select_profile_urls("https://acme.com", urls)

    assert selected == [
        "https://acme.com",
        "https://acme.com/product",
        "https://acme.com/solutions/revenue-operations",
    ]


def test_select_profile_urls_falls_back_to_about_or_pricing(service):
    urls = [
        "https://acme.com/about",
        "https://acme.com/pricing",
        "https://acme.com/contact",
    ]

    selected = service.select_profile_urls("https://acme.com", urls)

    assert selected[0] == "https://acme.com"
    assert "https://acme.com/pricing" in selected or "https://acme.com/about" in selected
    assert len(selected) <= 3
