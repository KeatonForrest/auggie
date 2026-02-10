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
    with patch("routes.research.save_document", new_callable=AsyncMock) as mock_save, \
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
async def test_view_document(authed_client, sample_research_document):
    """GET /document/{id} should return the document."""
    with patch("routes.research.get_document", new_callable=AsyncMock) as mock_get_doc, \
         patch("routes.research.get_all_documents", new_callable=AsyncMock, return_value=[]), \
         patch("routes.research.get_user_usage", new_callable=AsyncMock) as mock_usage, \
         patch("routes.research.get_enriched_contacts", new_callable=AsyncMock) as mock_contacts, \
         patch("routes.research.get_feedback", new_callable=AsyncMock) as mock_feedback:

        mock_get_doc.return_value = sample_research_document
        mock_usage.return_value = {"bonus_credits": 1000, "is_admin": False}
        mock_contacts.return_value = []
        mock_feedback.return_value = None

        response = await authed_client.get("/document/1")

        assert response.status_code == 200
        mock_get_doc.assert_called_once_with(1, user_id=1)


@pytest.mark.asyncio
async def test_document_not_found(authed_client):
    """GET /document/{id} should return 404 for missing documents."""
    with patch("routes.research.get_document", new_callable=AsyncMock) as mock_get_doc:
        mock_get_doc.return_value = None

        response = await authed_client.get("/document/999")

        assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_research(authed_client, mock_services, sample_research_document):
    """POST /api/research should return JSON response."""
    with patch("routes.research.save_document", new_callable=AsyncMock) as mock_save, \
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
