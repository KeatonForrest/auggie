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
async def test_research_creates_document(async_client, mock_services, sample_research_document):
    """POST /research should create a research document."""
    with patch("main.save_document", new_callable=AsyncMock) as mock_save, \
         patch("main.get_all_documents", new_callable=AsyncMock) as mock_get_docs:

        mock_save.return_value = 1  # Return doc ID
        mock_get_docs.return_value = [sample_research_document]

        response = await async_client.post(
            "/research",
            data={
                "company_url": "https://acme.com",
                "product_context": "MongoDB database solutions",
            }
        )

        assert response.status_code == 200
        mock_services["firecrawl"].scrape_company.assert_called_once()
        mock_services["wappalyzer"].analyze_multiple_domains.assert_called_once()
        mock_services["claude"].generate_research_document.assert_called_once()
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_view_document(async_client, sample_research_document):
    """GET /document/{id} should return the document."""
    with patch("main.get_document", new_callable=AsyncMock) as mock_get_doc, \
         patch("main.get_all_documents", new_callable=AsyncMock) as mock_get_docs:

        mock_get_doc.return_value = sample_research_document
        mock_get_docs.return_value = [sample_research_document]

        response = await async_client.get("/document/1")

        assert response.status_code == 200
        mock_get_doc.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_document_not_found(async_client):
    """GET /document/{id} should return 404 for missing documents."""
    with patch("main.get_document", new_callable=AsyncMock) as mock_get_doc:
        mock_get_doc.return_value = None

        response = await async_client.get("/document/999")

        assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_research(async_client, mock_services, sample_research_document):
    """POST /api/research should return JSON response."""
    with patch("main.save_document", new_callable=AsyncMock) as mock_save:
        mock_save.return_value = 1

        response = await async_client.post(
            "/api/research",
            json={
                "company_url": "https://acme.com",
                "product_context": "MongoDB database solutions",
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["document"] is not None


@pytest.mark.asyncio
async def test_api_list_documents(async_client, sample_research_document):
    """GET /api/documents should return list of documents."""
    with patch("main.get_all_documents", new_callable=AsyncMock) as mock_get_docs:
        mock_get_docs.return_value = [sample_research_document]

        response = await async_client.get("/api/documents")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1


@pytest.mark.asyncio
async def test_download_markdown(async_client, sample_research_document):
    """GET /document/{id}/markdown should return markdown file."""
    with patch("main.get_document", new_callable=AsyncMock) as mock_get_doc:
        mock_get_doc.return_value = sample_research_document

        response = await async_client.get("/document/1/markdown")

        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]
