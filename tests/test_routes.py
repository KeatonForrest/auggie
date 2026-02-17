"""
test_routes.py - API endpoint tests

Tests for FastAPI routes. External services are mocked so tests
run fast and don't hit real APIs.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.writing import SequenceValidationError


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


# ---------------------------------------------------------------------------
# LinkedIn message endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
def _enable_linkedin():
    """Enable the linkedin_message_enabled feature flag for the test."""
    with patch("routes.research.settings") as mock_settings:
        mock_settings.linkedin_message_enabled = True
        yield mock_settings


@pytest.mark.asyncio
async def test_linkedin_message_happy_path(authed_client, sample_research_document, _enable_linkedin):
    """POST /document/{id}/linkedin-message should return generated message."""
    result = {
        "message": "Acme Corp is scaling fast — have you considered a managed data layer?",
        "word_count": 13,
        "char_count": 68,
        "content_type": "none",
        "mode": "dm",
        "cta_rescued": False,
    }
    with patch("routes.research.get_document", new_callable=AsyncMock, return_value=sample_research_document), \
         patch("routes.research.writing_service") as mock_ws:
        mock_ws.generate_linkedin_message = AsyncMock(return_value=result)

        response = await authed_client.post(
            "/document/1/linkedin-message",
            data={"mode": "dm"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == result["message"]
    assert data["mode"] == "dm"


@pytest.mark.asyncio
async def test_linkedin_message_connection_request(authed_client, sample_research_document, _enable_linkedin):
    """POST /document/{id}/linkedin-message with mode=connection_request."""
    result = {
        "message": "Acme's growth is impressive — open to a quick chat about data infra?",
        "word_count": 13,
        "char_count": 67,
        "content_type": "none",
        "mode": "connection_request",
        "cta_rescued": False,
    }
    with patch("routes.research.get_document", new_callable=AsyncMock, return_value=sample_research_document), \
         patch("routes.research.writing_service") as mock_ws:
        mock_ws.generate_linkedin_message = AsyncMock(return_value=result)

        response = await authed_client.post(
            "/document/1/linkedin-message",
            data={"mode": "connection_request"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["mode"] == "connection_request"


@pytest.mark.asyncio
async def test_linkedin_message_invalid_mode(authed_client, sample_research_document, _enable_linkedin):
    """POST /document/{id}/linkedin-message with bad mode returns 422."""
    with patch("routes.research.get_document", new_callable=AsyncMock, return_value=sample_research_document):
        response = await authed_client.post(
            "/document/1/linkedin-message",
            data={"mode": "bad_mode"},
        )

    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "invalid_mode"


@pytest.mark.asyncio
async def test_linkedin_message_feature_flag_off(authed_client, sample_research_document):
    """POST /document/{id}/linkedin-message returns 404 when feature disabled."""
    with patch("routes.research.settings") as mock_settings:
        mock_settings.linkedin_message_enabled = False

        response = await authed_client.post(
            "/document/1/linkedin-message",
            data={"mode": "dm"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_linkedin_message_document_not_found(authed_client, _enable_linkedin):
    """POST /document/{id}/linkedin-message returns 404 for missing document."""
    with patch("routes.research.get_document", new_callable=AsyncMock, return_value=None):
        response = await authed_client.post(
            "/document/999/linkedin-message",
            data={"mode": "dm"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_linkedin_message_not_linkedin_screenshot(authed_client, sample_research_document, _enable_linkedin):
    """POST with a non-LinkedIn screenshot returns 422 with not_linkedin code."""
    with patch("routes.research.get_document", new_callable=AsyncMock, return_value=sample_research_document), \
         patch("routes.research.vision_service") as mock_vs:
        mock_vs.extract_linkedin_context = AsyncMock(return_value={"content_type": "other"})

        # Simulate file upload
        response = await authed_client.post(
            "/document/1/linkedin-message",
            data={"mode": "dm"},
            files={"screenshot": ("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png")},
        )

    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "not_linkedin"


@pytest.mark.asyncio
async def test_linkedin_message_validation_error(authed_client, sample_research_document, _enable_linkedin):
    """SequenceValidationError from writing service maps to 422."""
    with patch("routes.research.get_document", new_callable=AsyncMock, return_value=sample_research_document), \
         patch("routes.research.writing_service") as mock_ws:
        mock_ws.generate_linkedin_message = AsyncMock(
            side_effect=SequenceValidationError("quality_gate_failed", "Message failed quality checks"),
        )

        response = await authed_client.post(
            "/document/1/linkedin-message",
            data={"mode": "dm"},
        )

    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "quality_gate_failed"


@pytest.mark.asyncio
async def test_linkedin_message_generic_error(authed_client, sample_research_document, _enable_linkedin):
    """Unexpected exception maps to 500."""
    with patch("routes.research.get_document", new_callable=AsyncMock, return_value=sample_research_document), \
         patch("routes.research.writing_service") as mock_ws:
        mock_ws.generate_linkedin_message = AsyncMock(
            side_effect=RuntimeError("something broke"),
        )

        response = await authed_client.post(
            "/document/1/linkedin-message",
            data={"mode": "dm"},
        )

    assert response.status_code == 500
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "linkedin_generation_failed"
