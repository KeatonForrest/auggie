"""
test_routes.py - API endpoint tests

Tests for FastAPI routes. External services are mocked so tests
run fast and don't hit real APIs.
"""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_home_page_loads(async_client):
    """GET / should return 200 and render the home page."""
    with patch("main.get_all_documents", new_callable=AsyncMock) as mock_get_docs:
        mock_get_docs.return_value = []

        response = await async_client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_research_creates_document(authed_client, mock_services, sample_research_document):
    """POST /research/start should create a job and redirect to progress page."""
    with patch("routes.research.validate_company_url", side_effect=lambda url: url), \
         patch("routes.research.save_document", new_callable=AsyncMock) as mock_save, \
         patch("routes.research.get_user_usage", new_callable=AsyncMock) as mock_usage, \
         patch("routes.research.check_duplicate_research", new_callable=AsyncMock) as mock_dup, \
         patch("routes.research.create_job_with_credit", new_callable=AsyncMock) as mock_create_job, \
         patch("routes.research.create_tracked_task", new_callable=AsyncMock) as mock_task, \
         patch("db.documents.get_recent_document_by_url", new_callable=AsyncMock, return_value=None):

        mock_save.return_value = 1
        mock_usage.return_value = {"bonus_credits": 1000, "is_admin": False}
        mock_dup.return_value = None
        mock_create_job.return_value = {"id": 42}

        response = await authed_client.post(
            "/research/start",
            data={
                "company_url": "https://acme.com",
            },
            follow_redirects=False,
        )

        # Research start redirects to progress page
        assert response.status_code in (200, 303, 302)
        mock_create_job.assert_called_once()


@pytest.mark.asyncio
async def test_view_document_owner_redirects_to_slug(authed_client, fake_user, sample_research_document):
    """GET /document/{id} should 301 redirect owners to the slug URL."""
    with patch("routes.research.get_current_user", new_callable=AsyncMock, return_value=fake_user), \
         patch("routes.research.get_document", new_callable=AsyncMock) as mock_get_doc, \
         patch("routes.research.get_document_slug_path", new_callable=AsyncMock, return_value="/@user-1/acme-corp"):

        mock_get_doc.return_value = sample_research_document

        response = await authed_client.get("/document/1", follow_redirects=False)

        assert response.status_code == 301
        assert response.headers["location"] == "/@user-1/acme-corp"


@pytest.mark.asyncio
async def test_document_not_found(authed_client, fake_user):
    """GET /document/{id} should return 404 for missing documents."""
    with patch("routes.research.get_current_user", new_callable=AsyncMock, return_value=fake_user), \
         patch("routes.research.get_document", new_callable=AsyncMock) as mock_get_doc:
        mock_get_doc.return_value = None

        response = await authed_client.get("/document/999")

        assert response.status_code == 404


@pytest.mark.asyncio
async def test_view_document_non_owner_without_token(authed_client, fake_user):
    """GET /document/{id} should return 404 for non-owners without a share token."""
    with patch("routes.research.get_current_user", new_callable=AsyncMock, return_value=fake_user), \
         patch("routes.research.get_document", new_callable=AsyncMock) as mock_get_doc:
        mock_get_doc.return_value = None  # Not the owner

        response = await authed_client.get("/document/42")

        assert response.status_code == 404


@pytest.mark.asyncio
async def test_view_document_non_owner_with_invalid_token(authed_client, fake_user):
    """GET /document/{id} should return 404 for non-owners with wrong share token."""
    with patch("routes.research.get_current_user", new_callable=AsyncMock, return_value=fake_user), \
         patch("routes.research.get_document", new_callable=AsyncMock) as mock_get_doc, \
         patch("routes.research.get_document_by_share_token", new_callable=AsyncMock) as mock_shared:
        mock_get_doc.return_value = None  # Not the owner
        mock_shared.return_value = None   # Invalid token

        response = await authed_client.get("/document/42?token=bad-token")

        assert response.status_code == 404
        mock_shared.assert_called_once_with(42, "bad-token")


@pytest.mark.asyncio
async def test_view_document_non_owner_with_valid_token(authed_client, fake_user, sample_research_document):
    """GET /document/{id}?token=... should work for non-owners with a valid share token."""
    with patch("routes.research.get_current_user", new_callable=AsyncMock, return_value=fake_user), \
         patch("routes.research.get_document", new_callable=AsyncMock) as mock_get_doc, \
         patch("routes.research.get_document_by_share_token", new_callable=AsyncMock) as mock_shared, \
         patch("routes.research.get_all_documents", new_callable=AsyncMock, return_value=[]), \
         patch("routes.research.get_user_usage", new_callable=AsyncMock) as mock_usage:
        mock_get_doc.return_value = None  # Not the owner
        mock_shared.return_value = sample_research_document
        mock_usage.return_value = {"bonus_credits": 1000, "is_admin": False}

        response = await authed_client.get("/document/1?token=valid-share-token")

        assert response.status_code == 200
        mock_shared.assert_called_once_with(1, "valid-share-token")


@pytest.mark.asyncio
async def test_api_research(authed_client, mock_services, sample_research_document):
    """POST /api/research should return JSON response."""
    with patch("routes.research.validate_company_url", side_effect=lambda url: url), \
         patch("routes.research.save_document", new_callable=AsyncMock) as mock_save, \
         patch("routes.research.get_user_usage", new_callable=AsyncMock) as mock_usage, \
         patch("routes.research.check_duplicate_research", new_callable=AsyncMock) as mock_dup, \
         patch("routes.research.use_credit", new_callable=AsyncMock), \
         patch("routes.research.collect_enrichment_data", new_callable=AsyncMock, return_value=""):

        mock_save.return_value = 1
        mock_usage.return_value = {"bonus_credits": 1000, "is_admin": False}
        mock_dup.return_value = None

        response = await authed_client.post(
            "/api/research",
            json={
                "company_url": "https://acme.com",
                "product_context": "MongoDB database solutions",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


@pytest.mark.asyncio
async def test_research_rejects_unresolvable_url(authed_client):
    """POST /research/start with unresolvable hostname returns 400."""
    with patch("routes.research.validate_company_url", side_effect=ValueError("Cannot resolve hostname: no-such-host.invalid")):
        response = await authed_client.post(
            "/research/start",
            data={"company_url": "https://no-such-host.invalid"},
            follow_redirects=False,
        )

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "resolve" in data["error"].lower()


@pytest.mark.asyncio
async def test_api_research_rejects_unresolvable_url(authed_client):
    """POST /api/research with unresolvable hostname returns validation error."""
    with patch("routes.research.validate_company_url", side_effect=ValueError("Cannot resolve hostname: no-such-host.invalid")):
        response = await authed_client.post(
            "/api/research",
            json={"company_url": "https://no-such-host.invalid"},
        )

    assert response.status_code == 200  # API returns 200 with success=false
    data = response.json()
    assert data["success"] is False
    assert "resolve" in data["error"].lower()


@pytest.mark.asyncio
async def test_api_list_documents(authed_client, sample_research_document):
    """GET /api/documents should return list of documents."""
    with patch("routes.research.get_all_documents", new_callable=AsyncMock) as mock_get_docs:
        mock_get_docs.return_value = [sample_research_document]

        response = await authed_client.get("/api/documents")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1


@pytest.mark.asyncio
async def test_download_markdown(authed_client, sample_research_document):
    """GET /document/{id}/markdown should return markdown file."""
    with patch("routes.research.get_document", new_callable=AsyncMock) as mock_get_doc:
        mock_get_doc.return_value = sample_research_document

        response = await authed_client.get("/document/1/markdown")

        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]
