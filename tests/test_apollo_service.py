"""
test_apollo_service.py - Tests for Apollo.io integration service.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


# =============================================================================
# ApolloContact
# =============================================================================

class TestApolloContact:
    def test_to_dict(self):
        from services.apollo import ApolloContact
        c = ApolloContact(
            name="John Doe", title="CTO", email="john@acme.com",
            linkedin_url="https://linkedin.com/in/john", phone="+1234",
            seniority="vp", department="engineering",
        )
        d = c.to_dict()
        assert d["name"] == "John Doe"
        assert d["title"] == "CTO"
        assert d["email"] == "john@acme.com"
        assert d["linkedin_url"] == "https://linkedin.com/in/john"
        assert d["phone"] == "+1234"
        assert d["seniority"] == "vp"
        assert d["department"] == "engineering"

    def test_to_dict_optional_none(self):
        from services.apollo import ApolloContact
        c = ApolloContact(name="Jane", title="CEO")
        d = c.to_dict()
        assert d["email"] is None
        assert d["phone"] is None


# =============================================================================
# ApolloService
# =============================================================================

class TestApolloServiceSearchOrganization:
    @pytest.mark.asyncio
    async def test_returns_org_on_success(self):
        from services.apollo import ApolloService

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"organizations": [{"name": "Acme", "id": "org-1"}]}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()
            result = await svc._search_organization(mock_client, "acme.com")

        assert result["name"] == "Acme"

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        from services.apollo import ApolloService

        mock_resp = MagicMock(status_code=500, text="error")
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()
            result = await svc._search_organization(mock_client, "acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from services.apollo import ApolloService

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("fail")

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()
            result = await svc._search_organization(mock_client, "acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_orgs(self):
        from services.apollo import ApolloService

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"organizations": []}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()
            result = await svc._search_organization(mock_client, "acme.com")

        assert result is None


class TestApolloServiceSearchContacts:
    @pytest.mark.asyncio
    async def test_returns_contacts(self):
        from services.apollo import ApolloService

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "people": [
                {"first_name": "John", "last_name": "Doe", "title": "CTO", "email": "john@acme.com", "organization": {"name": "Acme"}},
            ]
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()
            contacts = await svc._search_contacts(mock_client, "acme.com")

        assert len(contacts) == 1
        assert contacts[0].name == "John Doe"
        assert contacts[0].title == "CTO"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        from services.apollo import ApolloService

        mock_resp = MagicMock(status_code=401, text="unauthorized")
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()
            contacts = await svc._search_contacts(mock_client, "acme.com")

        assert contacts == []

    @pytest.mark.asyncio
    async def test_handles_target_personas(self):
        from services.apollo import ApolloService

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"people": []}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()
            await svc._search_contacts(mock_client, "acme.com", target_personas="engineering, product")

        call_json = mock_client.post.call_args[1]["json"]
        assert "person_titles" in call_json
        assert len(call_json["person_titles"]) > 0

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self):
        from services.apollo import ApolloService

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("network error")

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()
            contacts = await svc._search_contacts(mock_client, "acme.com")

        assert contacts == []


class TestApolloServiceGetCompanyContacts:
    @pytest.mark.asyncio
    async def test_returns_none_without_api_key(self):
        from services.apollo import ApolloService

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="")
            svc = ApolloService()
            org, contacts = await svc.get_company_contacts("https://acme.com")

        assert org is None
        assert contacts == []

    @pytest.mark.asyncio
    async def test_cleans_domain(self):
        from services.apollo import ApolloService

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()

            with patch.object(svc, "_search_organization", new_callable=AsyncMock, return_value=None) as mock_org, \
                 patch.object(svc, "_search_contacts", new_callable=AsyncMock, return_value=[]) as mock_contacts:
                await svc.get_company_contacts("https://www.acme.com/about")

            # Should have cleaned domain
            mock_org.assert_called_once()
            args = mock_org.call_args[0]
            assert args[1] == "acme.com"


class TestApolloServiceFormatContacts:
    def test_formats_with_org_and_contacts(self):
        from services.apollo import ApolloService, ApolloContact

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()

        org = {"name": "Acme", "industry": "SaaS", "estimated_num_employees": 500}
        contacts = [ApolloContact(name="John", title="CTO", email="john@acme.com")]
        result = svc.format_contacts_for_prompt(org, contacts)

        assert "Acme" in result
        assert "SaaS" in result
        assert "John" in result
        assert "CTO" in result

    def test_returns_empty_when_nothing(self):
        from services.apollo import ApolloService

        with patch("services.apollo.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(apollo_api_key="key")
            svc = ApolloService()

        assert svc.format_contacts_for_prompt(None, []) == ""


# =============================================================================
# Integration functions
# =============================================================================

class TestApolloValidateApiKey:
    @pytest.mark.asyncio
    async def test_valid_key(self):
        from services.apollo import validate_integration_api_key

        mock_resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            assert await validate_integration_api_key("good-key") is True

    @pytest.mark.asyncio
    async def test_invalid_key(self):
        from services.apollo import validate_integration_api_key

        mock_resp = MagicMock(status_code=401)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            assert await validate_integration_api_key("bad-key") is False


class TestApolloGetIntegrationApiKey:
    @pytest.mark.asyncio
    async def test_returns_key(self):
        from services.apollo import _get_integration_api_key

        with patch("services.apollo.get_integration", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"access_token": "my-key"}
            key = await _get_integration_api_key(1)

        assert key == "my-key"

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        from services.apollo import _get_integration_api_key

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value=None):
            with pytest.raises(RuntimeError, match="Apollo not connected"):
                await _get_integration_api_key(1)


class TestApolloListSavedLists:
    @pytest.mark.asyncio
    async def test_returns_labels(self):
        from services.apollo import list_saved_lists

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"labels": [{"id": "l1", "name": "My List"}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            labels = await list_saved_lists(1)

        assert len(labels) == 1
        assert labels[0]["name"] == "My List"


class TestApolloFetchListCompanies:
    @pytest.mark.asyncio
    async def test_returns_companies(self):
        from services.apollo import fetch_list_companies

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"organizations": [{"name": "Acme"}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            data = await fetch_list_companies(1, "list-1")

        assert data["organizations"][0]["name"] == "Acme"


class TestApolloPushSequences:
    @pytest.mark.asyncio
    async def test_creates_sequences(self):
        from services.apollo import push_sequences_to_apollo

        accounts = [
            {"id": 1, "company_name": "Acme"},
            {"id": 2, "company_name": "Beta"},
        ]
        drafts = {
            1: [{"subject": "Hi", "body": "Hello"}],
            2: [{"subject": "Hey", "body": "World"}],
        }

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("services.apollo._create_apollo_sequence_with_emails", new_callable=AsyncMock, return_value="camp-1"):

            result = await push_sequences_to_apollo(1, accounts, drafts)

        assert result["sequences_created"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_skips_accounts_without_drafts(self):
        from services.apollo import push_sequences_to_apollo

        accounts = [{"id": 1, "company_name": "Acme"}, {"id": 2, "company_name": "Beta"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}]}

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("services.apollo._create_apollo_sequence_with_emails", new_callable=AsyncMock, return_value="camp-1"):

            result = await push_sequences_to_apollo(1, accounts, drafts)

        assert result["sequences_created"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_counts_errors(self):
        from services.apollo import push_sequences_to_apollo

        accounts = [{"id": 1, "company_name": "Acme"}]
        drafts = {1: [{"subject": "Hi", "body": "Hello"}]}

        with patch("services.apollo._get_integration_api_key", new_callable=AsyncMock, return_value="key"), \
             patch("services.apollo._create_apollo_sequence_with_emails", new_callable=AsyncMock, return_value=None):

            result = await push_sequences_to_apollo(1, accounts, drafts)

        assert result["errors"] == 1
        assert result["sequences_created"] == 0


class TestApolloCreateSequenceWithEmails:
    @pytest.mark.asyncio
    async def test_creates_campaign_and_steps(self):
        from services.apollo import _create_apollo_sequence_with_emails

        seq_resp = MagicMock(status_code=200)
        seq_resp.json.return_value = {"emailer_campaign": {"id": "camp-1"}}
        step_resp = MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [seq_resp, step_resp, step_resp]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _create_apollo_sequence_with_emails(
                "key", "Acme", [{"subject": "S1", "body": "B1"}, {"subject": "S2", "body": "B2"}],
            )

        assert result == "camp-1"
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_returns_none_on_create_failure(self):
        from services.apollo import _create_apollo_sequence_with_emails

        seq_resp = MagicMock(status_code=500, text="error")

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = seq_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await _create_apollo_sequence_with_emails("key", "Acme", [{"subject": "S", "body": "B"}])

        assert result is None


class TestApolloGetFirmographicsForUser:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_connected(self):
        from services.apollo import get_firmographics_for_user

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value=None):
            result = await get_firmographics_for_user(1, "https://acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_formatted_data(self):
        from services.apollo import get_firmographics_for_user

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "organizations": [{"name": "Acme", "industry": "SaaS", "estimated_num_employees": 500}]
        }

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value={"access_token": "key"}), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await get_firmographics_for_user(1, "https://acme.com")

        assert "Acme" in result
        assert "SaaS" in result
        assert "500" in result

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        from services.apollo import get_firmographics_for_user

        mock_resp = MagicMock(status_code=500)

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value={"access_token": "key"}), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await get_firmographics_for_user(1, "https://acme.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_only_name(self):
        from services.apollo import get_firmographics_for_user

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"organizations": [{"name": "Acme"}]}

        with patch("services.apollo.get_integration", new_callable=AsyncMock, return_value={"access_token": "key"}), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await get_firmographics_for_user(1, "https://acme.com")

        assert result is None


class TestApolloPlainToHtml:
    def test_escapes_and_converts(self):
        from services.apollo import _plain_to_html
        assert "&lt;" in _plain_to_html("<b>")
        assert "<br>" in _plain_to_html("a\nb")
        assert "</p><p>" in _plain_to_html("a\n\nb")
