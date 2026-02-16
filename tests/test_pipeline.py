"""
test_pipeline.py - Tests for Phase 10: Pipeline UI + Workflow Automation

Covers:
- Automation rules CRUD routes
- Automation rule evaluation engine
- Batch write sequences job
- Batch enrich stub
- Pipeline status endpoint
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# Platforms Hub
# =============================================================================

@pytest.mark.asyncio
async def test_platforms_page_loads(authed_client):
    """GET /platforms should render the hub page."""
    with patch("routes.platforms.get_user_usage", new_callable=AsyncMock, return_value={"bonus_credits": 1000, "is_admin": False}):
        response = await authed_client.get("/platforms")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Platforms" in response.text


@pytest.mark.asyncio
async def test_automations_redirects_to_platforms(authed_client):
    """GET /automations should 301 redirect to /platforms."""
    response = await authed_client.get("/automations", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/platforms"


# =============================================================================
# Automation Rule Evaluation Engine
# =============================================================================

class TestFilterByConditions:
    """Tests for services.automation.filter_by_conditions."""

    def test_no_conditions_returns_all_completed(self):
        from services.automation import filter_by_conditions
        accounts = [
            {"id": 1, "status": "completed", "composite_score": 80},
            {"id": 2, "status": "completed", "composite_score": 40},
            {"id": 3, "status": "failed", "composite_score": 90},
        ]
        result = filter_by_conditions(accounts, {})
        assert len(result) == 2
        assert all(a["status"] == "completed" for a in result)

    def test_composite_score_gte(self):
        from services.automation import filter_by_conditions
        accounts = [
            {"id": 1, "status": "completed", "composite_score": 80},
            {"id": 2, "status": "completed", "composite_score": 40},
            {"id": 3, "status": "completed", "composite_score": 70},
        ]
        result = filter_by_conditions(accounts, {"composite_score_gte": 70})
        assert len(result) == 2
        assert {a["id"] for a in result} == {1, 3}

    def test_pain_score_gte(self):
        from services.automation import filter_by_conditions
        accounts = [
            {"id": 1, "status": "completed", "pain_score": 90, "composite_score": 50},
            {"id": 2, "status": "completed", "pain_score": 30, "composite_score": 80},
        ]
        result = filter_by_conditions(accounts, {"pain_score_gte": 50})
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_multiple_conditions(self):
        from services.automation import filter_by_conditions
        accounts = [
            {"id": 1, "status": "completed", "composite_score": 80, "pain_score": 90},
            {"id": 2, "status": "completed", "composite_score": 80, "pain_score": 30},
            {"id": 3, "status": "completed", "composite_score": 40, "pain_score": 90},
        ]
        result = filter_by_conditions(accounts, {"composite_score_gte": 70, "pain_score_gte": 70})
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_none_scores_treated_as_zero(self):
        from services.automation import filter_by_conditions
        accounts = [
            {"id": 1, "status": "completed", "composite_score": None},
        ]
        result = filter_by_conditions(accounts, {"composite_score_gte": 50})
        assert len(result) == 0

    def test_empty_accounts(self):
        from services.automation import filter_by_conditions
        result = filter_by_conditions([], {"composite_score_gte": 50})
        assert result == []


class TestEvaluateRules:
    """Tests for services.automation.evaluate_rules."""

    @pytest.mark.asyncio
    async def test_no_rules_does_nothing(self):
        from services.automation import evaluate_rules
        with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[]):
            # Should not raise
            await evaluate_rules(1, "list_complete", {"list_id": 1, "accounts": []})

    @pytest.mark.asyncio
    async def test_matching_rule_executes_action(self):
        from services.automation import evaluate_rules
        fake_rule = {
            "id": 1, "name": "Test", "trigger_event": "list_complete",
            "conditions": {"composite_score_gte": 70},
            "action": "write_sequences", "action_config": {},
        }
        accounts = [{"id": 10, "status": "completed", "composite_score": 80}]

        with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[fake_rule]), \
             patch("services.automation.execute_action", new_callable=AsyncMock) as mock_exec:
            await evaluate_rules(1, "list_complete", {"list_id": 5, "accounts": accounts})
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args
            assert call_args[0][0] == fake_rule
            assert len(call_args[0][3]) == 1  # 1 matching account

    @pytest.mark.asyncio
    async def test_non_matching_rule_skipped(self):
        from services.automation import evaluate_rules
        fake_rule = {
            "id": 1, "name": "Test", "trigger_event": "list_complete",
            "conditions": {"composite_score_gte": 90},
            "action": "write_sequences", "action_config": {},
        }
        accounts = [{"id": 10, "status": "completed", "composite_score": 50}]

        with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[fake_rule]), \
             patch("services.automation.execute_action", new_callable=AsyncMock) as mock_exec:
            await evaluate_rules(1, "list_complete", {"list_id": 5, "accounts": accounts})
            mock_exec.assert_not_called()


# =============================================================================
# Automation Audit Trail
# =============================================================================

class TestExecuteActionAudit:
    """Tests that execute_action creates audit run records."""

    @pytest.mark.asyncio
    async def test_successful_action_logs_completed_run(self):
        from services.automation import execute_action
        rule = {"id": 1, "name": "Test", "action": "notify_slack", "action_config": {}}
        accounts = [{"id": 10, "status": "completed"}]

        fake_run = {"id": 99}
        with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=fake_run) as mock_create, \
             patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete, \
             patch("services.automation._action_notify_slack", new_callable=AsyncMock):
            await execute_action(rule, user_id=1, list_id=5, accounts=accounts)

            mock_create.assert_called_once_with(1, 1, 5, 1)
            mock_complete.assert_called_once_with(99, "completed")

    @pytest.mark.asyncio
    async def test_failed_action_logs_failed_run(self):
        from services.automation import execute_action
        rule = {"id": 2, "name": "Broken", "action": "push_instantly", "action_config": {}}
        accounts = [{"id": 10, "status": "completed"}]

        fake_run = {"id": 50}
        with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=fake_run) as mock_create, \
             patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete, \
             patch("services.automation._action_push_instantly", new_callable=AsyncMock, side_effect=RuntimeError("Instantly not connected")):
            await execute_action(rule, user_id=1, list_id=5, accounts=accounts)

            mock_create.assert_called_once_with(2, 1, 5, 1)
            mock_complete.assert_called_once()
            call_args = mock_complete.call_args[0]
            assert call_args[0] == 50
            assert call_args[1] == "failed"
            assert "Instantly not connected" in call_args[2]

    @pytest.mark.asyncio
    async def test_unknown_action_logs_failed(self):
        from services.automation import execute_action
        rule = {"id": 3, "name": "Bad", "action": "launch_missiles", "action_config": {}}
        accounts = [{"id": 10, "status": "completed"}]

        fake_run = {"id": 77}
        with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=fake_run), \
             patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete:
            await execute_action(rule, user_id=1, list_id=5, accounts=accounts)

            mock_complete.assert_called_once()
            assert mock_complete.call_args[0][1] == "failed"
            assert "Unknown action" in mock_complete.call_args[0][2]


class TestAutomationEvaluateRulesExceptionHandling:
    """Tests that evaluate_rules handles exceptions gracefully."""

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        """evaluate_rules should swallow exceptions gracefully."""
        from services.automation import evaluate_rules
        with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, side_effect=RuntimeError("db down")):
            # Should not raise
            await evaluate_rules(1, "list_complete", {"list_id": 1, "accounts": []})


# =============================================================================
# Pipeline Status Endpoint
# =============================================================================

@pytest.mark.asyncio
async def test_pipeline_status(authed_client):
    """GET /lists/{id}/pipeline-status should return step counts."""
    fake_list = {"id": 1, "user_id": 1, "name": "Test", "status": "completed",
                 "total_accounts": 3, "analyzed_accounts": 3, "failed_accounts": 0}
    fake_counts = {"scored": 3, "enriched": 1, "sequences_written": 2, "pushed": 1, "total": 3}
    with patch("routes.lists.get_list", new_callable=AsyncMock, return_value=fake_list), \
         patch("routes.lists.get_pipeline_counts", new_callable=AsyncMock, return_value=fake_counts):
        response = await authed_client.get("/lists/1/pipeline-status")
        assert response.status_code == 200
        data = response.json()
        assert data["scored"] == 3
        assert data["enriched"] == 1
        assert data["sequences_written"] == 2
        assert data["pushed"] == 1
        assert data["total"] == 3


@pytest.mark.asyncio
async def test_pipeline_status_list_not_found(authed_client):
    """GET /lists/{id}/pipeline-status for missing list should 404."""
    with patch("routes.lists.get_list", new_callable=AsyncMock, return_value=None):
        response = await authed_client.get("/lists/999/pipeline-status")
        assert response.status_code == 404


# =============================================================================
# Batch Enrich
# =============================================================================

@pytest.mark.asyncio
async def test_batch_enrich_no_provider_returns_422(authed_client):
    """POST /lists/{id}/batch-enrich with no providers connected should return 422."""
    fake_list = {"id": 1, "user_id": 1, "name": "Test", "status": "completed",
                 "total_accounts": 5, "analyzed_accounts": 5, "failed_accounts": 0}
    with patch("routes.lists.get_list", new_callable=AsyncMock, return_value=fake_list), \
         patch("services.enrichment.get_integration", new_callable=AsyncMock, return_value=None):
        response = await authed_client.post("/lists/1/batch-enrich", json={"account_ids": [1, 2]})
        assert response.status_code == 422
        data = response.json()
        assert data["success"] is False
        assert "provider" in data["error"].lower()


@pytest.mark.asyncio
async def test_batch_enrich_with_provider_queues_task(authed_client):
    """POST /lists/{id}/batch-enrich with a provider connected should queue task."""
    fake_list = {"id": 1, "user_id": 1, "name": "Test", "status": "completed",
                 "total_accounts": 5, "analyzed_accounts": 5, "failed_accounts": 0}
    fake_integration = {"id": 1, "access_token": "test-key"}
    with patch("routes.lists.get_list", new_callable=AsyncMock, return_value=fake_list), \
         patch("services.enrichment.get_integration", new_callable=AsyncMock, return_value=fake_integration), \
         patch("routes.lists.create_tracked_task", new_callable=AsyncMock), \
         patch("routes.lists.count_ready_accounts", new_callable=AsyncMock, return_value=3):
        response = await authed_client.post("/lists/1/batch-enrich", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["queued_count"] == 3


@pytest.mark.asyncio
async def test_batch_enrich_list_not_found(authed_client):
    """POST /lists/{id}/batch-enrich for missing list should 404."""
    with patch("routes.lists.get_list", new_callable=AsyncMock, return_value=None):
        response = await authed_client.post("/lists/999/batch-enrich", json={})
        assert response.status_code == 404


# =============================================================================
# Batch Write Sequences
# =============================================================================

@pytest.mark.asyncio
async def test_batch_write_sequences_route(authed_client):
    """POST /lists/{id}/batch-write-sequences should queue the job."""
    fake_list = {"id": 1, "user_id": 1, "name": "Test", "status": "completed",
                 "total_accounts": 2, "analyzed_accounts": 2, "failed_accounts": 0}
    with patch("routes.lists.get_list", new_callable=AsyncMock, return_value=fake_list), \
         patch("routes.lists.count_ready_accounts", new_callable=AsyncMock, return_value=2), \
         patch("routes.lists.create_tracked_task", new_callable=AsyncMock):
        response = await authed_client.post("/lists/1/batch-write-sequences", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["queued_count"] == 2


@pytest.mark.asyncio
async def test_batch_write_sequences_with_selection(authed_client):
    """POST /lists/{id}/batch-write-sequences with account_ids filters correctly."""
    fake_list = {"id": 1, "user_id": 1, "name": "Test", "status": "completed",
                 "total_accounts": 2, "analyzed_accounts": 2, "failed_accounts": 0}
    with patch("routes.lists.get_list", new_callable=AsyncMock, return_value=fake_list), \
         patch("routes.lists.count_ready_accounts", new_callable=AsyncMock, return_value=1), \
         patch("routes.lists.create_tracked_task", new_callable=AsyncMock):
        response = await authed_client.post("/lists/1/batch-write-sequences", json={"account_ids": [1]})
        assert response.status_code == 200
        assert response.json()["queued_count"] == 1


@pytest.mark.asyncio
async def test_batch_write_sequences_list_not_found(authed_client):
    """POST /lists/{id}/batch-write-sequences for missing list should 404."""
    with patch("routes.lists.get_list", new_callable=AsyncMock, return_value=None):
        response = await authed_client.post("/lists/999/batch-write-sequences", json={})
        assert response.status_code == 404


# =============================================================================
# Batch Write Sequences Job Logic
# =============================================================================

class TestRunBatchWriteSequences:
    """Tests for api.jobs.run_batch_write_sequences."""

    @pytest.mark.asyncio
    async def test_processes_completed_accounts(self, sample_research_document):
        from api.jobs import run_batch_write_sequences
        fake_accounts = [
            {"id": 1, "status": "completed", "document_id": 10, "enrichment_status": "none", "outreach_status": "none"},
            {"id": 2, "status": "failed", "document_id": None, "enrichment_status": "none", "outreach_status": "none"},
        ]
        fake_user = {"id": 1, "product_context": "test context"}
        fake_emails = [{"email_number": 1, "subject": "Hi", "body": "Hello"}]

        with patch("database.get_list_accounts", new_callable=AsyncMock, return_value=fake_accounts), \
             patch("api.jobs.get_user_by_id", new_callable=AsyncMock, return_value=fake_user), \
             patch("database.get_document", new_callable=AsyncMock, return_value=sample_research_document), \
             patch("database.update_list_account_outreach", new_callable=AsyncMock) as mock_outreach, \
             patch("database.save_outreach_draft", new_callable=AsyncMock, return_value=1), \
             patch("services.instances.writing_service") as mock_writing:

            mock_writing.generate_email_sequence = AsyncMock(return_value=(fake_emails, ["Subject option"]))

            await run_batch_write_sequences(list_id=1, user_id=1)

            # Should have set pending then completed for account 1, skipped account 2
            outreach_calls = mock_outreach.call_args_list
            statuses = [(c[0][0], c[0][1]) for c in outreach_calls]
            assert (1, "pending") in statuses
            assert (1, "completed") in statuses
            # Account 2 (failed) should not appear
            assert all(s[0] != 2 for s in statuses)

    @pytest.mark.asyncio
    async def test_handles_missing_user(self):
        from api.jobs import run_batch_write_sequences
        with patch("database.get_list_accounts", new_callable=AsyncMock, return_value=[]), \
             patch("api.jobs.get_user_by_id", new_callable=AsyncMock, return_value=None):
            # Should return early, not raise
            await run_batch_write_sequences(list_id=1, user_id=999)

    @pytest.mark.asyncio
    async def test_failed_generation_sets_failed_status(self, sample_research_document):
        from api.jobs import run_batch_write_sequences
        fake_accounts = [
            {"id": 1, "status": "completed", "document_id": 10, "enrichment_status": "none", "outreach_status": "none"},
        ]
        fake_user = {"id": 1, "product_context": "test"}

        with patch("database.get_list_accounts", new_callable=AsyncMock, return_value=fake_accounts), \
             patch("api.jobs.get_user_by_id", new_callable=AsyncMock, return_value=fake_user), \
             patch("database.get_document", new_callable=AsyncMock, return_value=sample_research_document), \
             patch("database.update_list_account_outreach", new_callable=AsyncMock) as mock_outreach, \
             patch("database.save_outreach_draft", new_callable=AsyncMock), \
             patch("services.instances.writing_service") as mock_writing:

            mock_writing.generate_email_sequence = AsyncMock(side_effect=RuntimeError("LLM error"))

            await run_batch_write_sequences(list_id=1, user_id=1)

            statuses = [(c[0][0], c[0][1]) for c in mock_outreach.call_args_list]
            assert (1, "pending") in statuses
            assert (1, "failed") in statuses
