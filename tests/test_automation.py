"""Tests for services/automation.py"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


# Import the module under test
from services.automation import (
    filter_by_conditions,
    execute_action,
    evaluate_rules,
    _action_push_instantly,
    _action_push_smartlead,
    _action_push_outreach,
    _action_push_salesloft,
    _action_write_sequences,
    _action_notify_slack,
)


# ============================================================================
# filter_by_conditions tests
# ============================================================================


def test_filter_by_conditions_all_conditions():
    """Test filtering with all score conditions."""
    accounts = [
        {"id": 1, "status": "completed", "composite_score": 80, "pain_score": 70, "fit_score": 90, "timing_score": 60},
        {"id": 2, "status": "completed", "composite_score": 50, "pain_score": 40, "fit_score": 60, "timing_score": 30},
    ]
    conditions = {
        "composite_score_gte": 70,
        "pain_score_gte": 60,
        "fit_score_gte": 80,
        "timing_score_gte": 50,
    }
    result = filter_by_conditions(accounts, conditions)
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_filter_by_conditions_partial_match():
    """Test filtering with partial conditions."""
    accounts = [
        {"id": 1, "status": "completed", "composite_score": 80},
        {"id": 2, "status": "completed", "composite_score": 50},
    ]
    conditions = {"composite_score_gte": 70}
    result = filter_by_conditions(accounts, conditions)
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_filter_by_conditions_no_match():
    """Test filtering with no matching accounts."""
    accounts = [
        {"id": 1, "status": "completed", "composite_score": 50},
        {"id": 2, "status": "completed", "composite_score": 60},
    ]
    conditions = {"composite_score_gte": 80}
    result = filter_by_conditions(accounts, conditions)
    assert len(result) == 0


def test_filter_by_conditions_skips_non_completed():
    """Test that non-completed accounts are skipped."""
    accounts = [
        {"id": 1, "status": "pending", "composite_score": 80},
        {"id": 2, "status": "completed", "composite_score": 80},
        {"id": 3, "status": "failed", "composite_score": 80},
    ]
    conditions = {"composite_score_gte": 70}
    result = filter_by_conditions(accounts, conditions)
    assert len(result) == 1
    assert result[0]["id"] == 2


def test_filter_by_conditions_handles_none_scores():
    """Test that None scores are treated as 0."""
    accounts = [
        {"id": 1, "status": "completed", "composite_score": None},
        {"id": 2, "status": "completed"},  # Missing score entirely
        {"id": 3, "status": "completed", "composite_score": 50},
    ]
    conditions = {"composite_score_gte": 40}
    result = filter_by_conditions(accounts, conditions)
    assert len(result) == 1
    assert result[0]["id"] == 3


def test_filter_by_conditions_empty_conditions_matches_all_completed():
    """Test that empty conditions matches all completed accounts."""
    accounts = [
        {"id": 1, "status": "completed", "composite_score": 80},
        {"id": 2, "status": "completed", "composite_score": 50},
        {"id": 3, "status": "pending", "composite_score": 90},
    ]
    conditions = {}
    result = filter_by_conditions(accounts, conditions)
    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["id"] == 2


def test_filter_by_conditions_multiple_scores():
    """Test filtering with multiple score conditions."""
    accounts = [
        {"id": 1, "status": "completed", "pain_score": 70, "fit_score": 80},
        {"id": 2, "status": "completed", "pain_score": 50, "fit_score": 80},
        {"id": 3, "status": "completed", "pain_score": 70, "fit_score": 60},
    ]
    conditions = {
        "pain_score_gte": 60,
        "fit_score_gte": 70,
    }
    result = filter_by_conditions(accounts, conditions)
    assert len(result) == 1
    assert result[0]["id"] == 1


# ============================================================================
# execute_action tests
# ============================================================================


@pytest.mark.asyncio
async def test_execute_action_push_instantly_deprecated():
    """Test execute_action marks deprecated push_instantly as failed."""
    rule = {"id": 1, "action": "push_instantly", "action_config": {"campaign_id": "123"}}
    accounts = [{"id": 1}]
    run = {"id": 100}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete:

        await execute_action(rule, user_id=1, list_id=10, accounts=accounts)

        mock_create.assert_called_once_with(1, 1, 10, 1)
        mock_complete.assert_called_once()
        call_args = mock_complete.call_args[0]
        assert call_args[0] == 100
        assert call_args[1] == "failed"
        assert "deprecated" in call_args[2].lower()


@pytest.mark.asyncio
async def test_execute_action_push_smartlead_deprecated():
    """Test execute_action marks deprecated push_smartlead as failed."""
    rule = {"id": 2, "action": "push_smartlead", "action_config": {"campaign_id": "456"}}
    accounts = [{"id": 2}]
    run = {"id": 101}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete:

        await execute_action(rule, user_id=2, list_id=20, accounts=accounts)

        mock_create.assert_called_once_with(2, 2, 20, 1)
        mock_complete.assert_called_once()
        call_args = mock_complete.call_args[0]
        assert call_args[0] == 101
        assert call_args[1] == "failed"
        assert "deprecated" in call_args[2].lower()


@pytest.mark.asyncio
async def test_execute_action_push_outreach_deprecated():
    """Test execute_action marks deprecated push_outreach as failed."""
    rule = {"id": 3, "action": "push_outreach"}
    accounts = [{"id": 3}]
    run = {"id": 102}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete:

        await execute_action(rule, user_id=3, list_id=30, accounts=accounts)

        mock_create.assert_called_once_with(3, 3, 30, 1)
        mock_complete.assert_called_once()
        call_args = mock_complete.call_args[0]
        assert call_args[0] == 102
        assert call_args[1] == "failed"
        assert "deprecated" in call_args[2].lower()


@pytest.mark.asyncio
async def test_execute_action_push_salesloft_deprecated():
    """Test execute_action marks deprecated push_salesloft as failed."""
    rule = {"id": 4, "action": "push_salesloft"}
    accounts = [{"id": 4}]
    run = {"id": 103}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete:

        await execute_action(rule, user_id=4, list_id=40, accounts=accounts)

        mock_create.assert_called_once_with(4, 4, 40, 1)
        mock_complete.assert_called_once()
        call_args = mock_complete.call_args[0]
        assert call_args[0] == 103
        assert call_args[1] == "failed"
        assert "deprecated" in call_args[2].lower()


@pytest.mark.asyncio
async def test_execute_action_write_sequences():
    """Test execute_action dispatches to write_sequences correctly."""
    rule = {"id": 5, "action": "write_sequences"}
    accounts = [{"id": 5}]
    run = {"id": 104}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete, \
         patch("services.automation._action_write_sequences", new_callable=AsyncMock) as mock_action:

        await execute_action(rule, user_id=5, list_id=50, accounts=accounts)

        mock_create.assert_called_once_with(5, 5, 50, 1)
        mock_action.assert_called_once_with(rule, 5, 50, accounts)
        mock_complete.assert_called_once_with(104, "completed")


@pytest.mark.asyncio
async def test_execute_action_notify_slack():
    """Test execute_action dispatches to notify_slack correctly."""
    rule = {"id": 6, "action": "notify_slack", "action_config": {"channel": "#general"}}
    accounts = [{"id": 6}]
    run = {"id": 105}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete, \
         patch("services.automation._action_notify_slack", new_callable=AsyncMock) as mock_action:

        await execute_action(rule, user_id=6, list_id=60, accounts=accounts)

        mock_create.assert_called_once_with(6, 6, 60, 1)
        mock_action.assert_called_once_with(rule, 6, 60, accounts, {"channel": "#general"})
        mock_complete.assert_called_once_with(105, "completed")


@pytest.mark.asyncio
async def test_execute_action_unknown_action_marks_failed():
    """Test that unknown action marks run as failed."""
    rule = {"id": 7, "action": "unknown_action"}
    accounts = [{"id": 7}]
    run = {"id": 106}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete:

        await execute_action(rule, user_id=7, list_id=70, accounts=accounts)

        mock_create.assert_called_once_with(7, 7, 70, 1)
        mock_complete.assert_called_once_with(106, "failed", "Unknown action: unknown_action")


@pytest.mark.asyncio
async def test_execute_action_exception_marks_failed():
    """Test that exception in action marks run as failed."""
    rule = {"id": 8, "action": "notify_slack", "action_config": {}}
    accounts = [{"id": 8}]
    run = {"id": 107}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete, \
         patch("services.automation._action_notify_slack", new_callable=AsyncMock, side_effect=RuntimeError("Test error")) as mock_action:

        await execute_action(rule, user_id=8, list_id=80, accounts=accounts)

        mock_create.assert_called_once_with(8, 8, 80, 1)
        mock_action.assert_called_once()
        mock_complete.assert_called_once_with(107, "failed", "Test error")


@pytest.mark.asyncio
async def test_execute_action_long_error_truncated():
    """Test that long error messages are truncated to 500 chars."""
    rule = {"id": 9, "action": "notify_slack", "action_config": {}}
    accounts = [{"id": 9}]
    run = {"id": 108}
    long_error = "x" * 600

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete, \
         patch("services.automation._action_notify_slack", new_callable=AsyncMock, side_effect=RuntimeError(long_error)) as mock_action:

        await execute_action(rule, user_id=9, list_id=90, accounts=accounts)

        mock_create.assert_called_once_with(9, 9, 90, 1)
        mock_action.assert_called_once()
        # Verify error was truncated to 500 chars
        call_args = mock_complete.call_args[0]
        assert len(call_args[2]) == 500


@pytest.mark.asyncio
async def test_execute_action_no_action_config():
    """Test execute_action with missing action_config."""
    rule = {"id": 10, "action": "write_sequences"}  # No action_config
    accounts = [{"id": 10}]
    run = {"id": 109}

    with patch("services.automation.create_automation_run", new_callable=AsyncMock, return_value=run) as mock_create, \
         patch("services.automation.complete_automation_run", new_callable=AsyncMock) as mock_complete, \
         patch("services.automation._action_write_sequences", new_callable=AsyncMock) as mock_action:

        await execute_action(rule, user_id=10, list_id=100, accounts=accounts)

        mock_create.assert_called_once_with(10, 10, 100, 1)
        mock_action.assert_called_once_with(rule, 10, 100, accounts)
        mock_complete.assert_called_once_with(109, "completed")


# ============================================================================
# _action_push_instantly tests
# ============================================================================


@pytest.mark.asyncio
async def test_action_push_instantly_not_connected_raises():
    """Test push_instantly raises when integration not connected."""
    rule = {"id": 1}
    config = {"campaign_id": "123"}
    accounts = [{"id": 1, "document_id": "doc1"}]

    with patch("database.get_integration", new_callable=AsyncMock, return_value=None):
        with pytest.raises(RuntimeError, match="Instantly not connected"):
            await _action_push_instantly(rule, user_id=1, config=config, accounts=accounts)


@pytest.mark.asyncio
async def test_action_push_instantly_no_campaign_id_raises():
    """Test push_instantly raises when no campaign_id configured."""
    rule = {"id": 1}
    config = {}  # No campaign_id
    accounts = [{"id": 1}]

    with patch("database.get_integration", new_callable=AsyncMock, return_value={"id": 1}):
        with pytest.raises(RuntimeError, match="No campaign_id configured"):
            await _action_push_instantly(rule, user_id=1, config=config, accounts=accounts)


@pytest.mark.asyncio
async def test_action_push_instantly_success():
    """Test push_instantly successfully pushes accounts."""
    rule = {"id": 1}
    config = {"campaign_id": "123"}
    accounts = [
        {"id": 1, "document_id": "doc1"},
        {"id": 2, "document_id": "doc2"},
        {"id": 3},  # No document_id
    ]
    contacts = [{"email": "test@example.com"}]

    with patch("database.get_integration", new_callable=AsyncMock, return_value={"id": 1}) as mock_integration, \
         patch("database.get_enriched_contacts", new_callable=AsyncMock, return_value=contacts) as mock_contacts, \
         patch("services.instantly.push_accounts_to_instantly", new_callable=AsyncMock, return_value={"pushed": 2}) as mock_push:

        await _action_push_instantly(rule, user_id=1, config=config, accounts=accounts)

        mock_integration.assert_called_once_with(1, "instantly")
        # Should get contacts for accounts with document_id
        assert mock_contacts.call_count == 2
        mock_contacts.assert_any_call("doc1", 1)
        mock_contacts.assert_any_call("doc2", 1)

        # Verify push was called with correct params
        call_args = mock_push.call_args[0]
        assert call_args[0] == 1  # user_id
        assert call_args[1] == "123"  # campaign_id
        assert call_args[2] == accounts  # accounts
        assert len(call_args[3]) == 2  # contacts_by_account


@pytest.mark.asyncio
async def test_action_push_instantly_no_contacts():
    """Test push_instantly when no contacts are found."""
    rule = {"id": 1}
    config = {"campaign_id": "123"}
    accounts = [{"id": 1, "document_id": "doc1"}]

    with patch("database.get_integration", new_callable=AsyncMock, return_value={"id": 1}), \
         patch("database.get_enriched_contacts", new_callable=AsyncMock, return_value=None) as mock_contacts, \
         patch("services.instantly.push_accounts_to_instantly", new_callable=AsyncMock, return_value={"pushed": 0}) as mock_push:

        await _action_push_instantly(rule, user_id=1, config=config, accounts=accounts)

        mock_contacts.assert_called_once_with("doc1", 1)
        # Should still call push with empty contacts_by_account
        call_args = mock_push.call_args[0]
        assert call_args[3] == {}  # contacts_by_account


# ============================================================================
# _action_push_smartlead tests
# ============================================================================


@pytest.mark.asyncio
async def test_action_push_smartlead_not_connected_raises():
    """Test push_smartlead raises when integration not connected."""
    rule = {"id": 2}
    config = {"campaign_id": "456"}
    accounts = [{"id": 2}]

    with patch("database.get_integration", new_callable=AsyncMock, return_value=None):
        with pytest.raises(RuntimeError, match="Smartlead not connected"):
            await _action_push_smartlead(rule, user_id=2, config=config, accounts=accounts)


@pytest.mark.asyncio
async def test_action_push_smartlead_no_campaign_id_raises():
    """Test push_smartlead raises when no campaign_id configured."""
    rule = {"id": 2}
    config = {}
    accounts = [{"id": 2}]

    with patch("database.get_integration", new_callable=AsyncMock, return_value={"id": 2}):
        with pytest.raises(RuntimeError, match="No campaign_id configured"):
            await _action_push_smartlead(rule, user_id=2, config=config, accounts=accounts)


@pytest.mark.asyncio
async def test_action_push_smartlead_success():
    """Test push_smartlead successfully pushes accounts."""
    rule = {"id": 2}
    config = {"campaign_id": "456"}
    accounts = [{"id": 2, "document_id": "doc2"}]
    contacts = [{"email": "test@example.com"}]

    with patch("database.get_integration", new_callable=AsyncMock, return_value={"id": 2}), \
         patch("database.get_enriched_contacts", new_callable=AsyncMock, return_value=contacts), \
         patch("services.smartlead.push_accounts_to_smartlead", new_callable=AsyncMock, return_value={"pushed": 1}) as mock_push:

        await _action_push_smartlead(rule, user_id=2, config=config, accounts=accounts)

        call_args = mock_push.call_args[0]
        assert call_args[0] == 2  # user_id
        assert call_args[1] == "456"  # campaign_id


# ============================================================================
# _action_push_outreach tests
# ============================================================================


@pytest.mark.asyncio
async def test_action_push_outreach_no_drafts_raises():
    """Test push_outreach raises when no drafts found."""
    rule = {"id": 3}
    accounts = [{"id": 3, "document_id": "doc3"}]

    with patch("database.get_outreach_draft", new_callable=AsyncMock, return_value=None):
        with pytest.raises(RuntimeError, match="No written sequences found"):
            await _action_push_outreach(rule, user_id=3, accounts=accounts)


@pytest.mark.asyncio
async def test_action_push_outreach_empty_emails_raises():
    """Test push_outreach raises when draft has no emails."""
    rule = {"id": 3}
    accounts = [{"id": 3, "document_id": "doc3"}]
    draft = {"content": json.dumps({"emails": []})}

    with patch("database.get_outreach_draft", new_callable=AsyncMock, return_value=draft):
        with pytest.raises(RuntimeError, match="No written sequences found"):
            await _action_push_outreach(rule, user_id=3, accounts=accounts)


@pytest.mark.asyncio
async def test_action_push_outreach_success_with_json_string():
    """Test push_outreach with JSON string content."""
    rule = {"id": 3}
    accounts = [{"id": 3, "document_id": "doc3"}]
    emails = [{"subject": "Test", "body": "Hello"}]
    draft = {"content": json.dumps({"emails": emails})}

    with patch("database.get_outreach_draft", new_callable=AsyncMock, return_value=draft), \
         patch("services.outreach.push_sequences_to_outreach", new_callable=AsyncMock, return_value={"sequences_created": 1}) as mock_push:

        await _action_push_outreach(rule, user_id=3, accounts=accounts)

        call_args = mock_push.call_args[0]
        assert call_args[0] == 3  # user_id
        assert call_args[1] == accounts
        assert call_args[2] == {3: emails}


@pytest.mark.asyncio
async def test_action_push_outreach_success_with_dict_content():
    """Test push_outreach with dict content."""
    rule = {"id": 3}
    accounts = [{"id": 3, "document_id": "doc3"}]
    emails = [{"subject": "Test", "body": "Hello"}]
    draft = {"content": {"emails": emails}}

    with patch("database.get_outreach_draft", new_callable=AsyncMock, return_value=draft), \
         patch("services.outreach.push_sequences_to_outreach", new_callable=AsyncMock, return_value={"sequences_created": 1}) as mock_push:

        await _action_push_outreach(rule, user_id=3, accounts=accounts)

        call_args = mock_push.call_args[0]
        assert call_args[2] == {3: emails}


@pytest.mark.asyncio
async def test_action_push_outreach_skips_accounts_without_document_id():
    """Test push_outreach skips accounts without document_id."""
    rule = {"id": 3}
    accounts = [
        {"id": 3, "document_id": "doc3"},
        {"id": 4},  # No document_id
    ]
    emails = [{"subject": "Test", "body": "Hello"}]
    draft = {"content": {"emails": emails}}

    with patch("database.get_outreach_draft", new_callable=AsyncMock, return_value=draft) as mock_draft, \
         patch("services.outreach.push_sequences_to_outreach", new_callable=AsyncMock, return_value={"sequences_created": 1}) as mock_push:

        await _action_push_outreach(rule, user_id=3, accounts=accounts)

        # Should only fetch draft for account with document_id
        mock_draft.assert_called_once_with("doc3")
        call_args = mock_push.call_args[0]
        assert call_args[2] == {3: emails}


# ============================================================================
# _action_push_salesloft tests
# ============================================================================


@pytest.mark.asyncio
async def test_action_push_salesloft_no_drafts_raises():
    """Test push_salesloft raises when no drafts found."""
    rule = {"id": 4}
    accounts = [{"id": 4, "document_id": "doc4"}]

    with patch("database.get_outreach_draft", new_callable=AsyncMock, return_value=None):
        with pytest.raises(RuntimeError, match="No written sequences found"):
            await _action_push_salesloft(rule, user_id=4, accounts=accounts)


@pytest.mark.asyncio
async def test_action_push_salesloft_success():
    """Test push_salesloft successfully pushes sequences."""
    rule = {"id": 4}
    accounts = [{"id": 4, "document_id": "doc4"}]
    emails = [{"subject": "Test", "body": "Hello"}]
    draft = {"content": {"emails": emails}}

    with patch("database.get_outreach_draft", new_callable=AsyncMock, return_value=draft), \
         patch("services.salesloft.push_sequences_to_salesloft", new_callable=AsyncMock, return_value={"cadences_created": 1}) as mock_push:

        await _action_push_salesloft(rule, user_id=4, accounts=accounts)

        call_args = mock_push.call_args[0]
        assert call_args[0] == 4  # user_id
        assert call_args[1] == accounts
        assert call_args[2] == {4: emails}


# ============================================================================
# _action_write_sequences tests
# ============================================================================


@pytest.mark.asyncio
async def test_action_write_sequences_calls_correctly():
    """Test write_sequences calls run_batch_write_sequences correctly."""
    rule = {"id": 5}
    accounts = [{"id": 5}, {"id": 6}, {"id": 7}]

    with patch("api.jobs.run_batch_write_sequences", new_callable=AsyncMock) as mock_run:
        await _action_write_sequences(rule, user_id=5, list_id=50, accounts=accounts)

        mock_run.assert_called_once_with(50, 5, account_ids=[5, 6, 7])


@pytest.mark.asyncio
async def test_action_write_sequences_empty_accounts():
    """Test write_sequences with empty accounts list."""
    rule = {"id": 5}
    accounts = []

    with patch("api.jobs.run_batch_write_sequences", new_callable=AsyncMock) as mock_run:
        await _action_write_sequences(rule, user_id=5, list_id=50, accounts=accounts)

        mock_run.assert_called_once_with(50, 5, account_ids=[])


# ============================================================================
# _action_notify_slack tests
# ============================================================================


@pytest.mark.asyncio
async def test_action_notify_slack_not_connected_raises():
    """Test notify_slack raises when Slack not connected."""
    rule = {"id": 6, "name": "Test Rule"}
    accounts = [{"id": 6}]
    config = {}

    with patch("database.get_integration", new_callable=AsyncMock, return_value=None):
        with pytest.raises(RuntimeError, match="No notification channel connected"):
            await _action_notify_slack(rule, user_id=6, list_id=60, accounts=accounts, config=config)


@pytest.mark.asyncio
async def test_action_notify_slack_success():
    """Test notify_slack successfully sends notification."""
    rule = {"id": 6, "name": "Test Rule"}
    accounts = [{"id": 6}, {"id": 7}]
    config = {}
    slack_integration = {"access_token": "xoxb-token"}

    with patch("database.get_integration", new_callable=AsyncMock, return_value=slack_integration), \
         patch("config.get_settings", return_value=MagicMock(app_url="https://app.example.com")), \
         patch("services.notifications.send_slack_notification", new_callable=AsyncMock) as mock_send:

        await _action_notify_slack(rule, user_id=6, list_id=60, accounts=accounts, config=config)

        mock_send.assert_called_once()
        call_args = mock_send.call_args[0]
        assert call_args[0] == "xoxb-token"
        assert call_args[1] == "list_complete"
        notification_data = call_args[2]
        assert notification_data["list_name"] == "Automation: Test Rule"
        assert notification_data["total_accounts"] == 2
        assert notification_data["completed_accounts"] == 2
        assert notification_data["failed_accounts"] == 0
        assert notification_data["list_url"] == "https://app.example.com/lists/60"


# ============================================================================
# evaluate_rules tests
# ============================================================================


@pytest.mark.asyncio
async def test_evaluate_rules_no_rules_returns_early():
    """Test evaluate_rules returns early when no rules found."""
    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[]) as mock_get_rules:
        await evaluate_rules(user_id=1, trigger_event="list_complete", context={})

        mock_get_rules.assert_called_once_with(1, "list_complete")


@pytest.mark.asyncio
async def test_evaluate_rules_conditions_as_json_string():
    """Test evaluate_rules parses JSON string conditions."""
    rule = {
        "id": 1,
        "action": "notify_slack",
        "name": "Test",
        "conditions": json.dumps({"composite_score_gte": 70}),
    }
    accounts = [
        {"id": 1, "status": "completed", "composite_score": 80},
        {"id": 2, "status": "completed", "composite_score": 60},
    ]
    context = {"list_id": 10, "accounts": accounts}

    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[rule]), \
         patch("services.automation.execute_action", new_callable=AsyncMock) as mock_execute:

        await evaluate_rules(user_id=1, trigger_event="list_complete", context=context)

        # Should execute with only account 1
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args[0]
        assert call_args[0] == rule
        assert call_args[1] == 1
        assert call_args[2] == 10
        assert len(call_args[3]) == 1
        assert call_args[3][0]["id"] == 1


@pytest.mark.asyncio
async def test_evaluate_rules_conditions_as_dict():
    """Test evaluate_rules with dict conditions."""
    rule = {
        "id": 2,
        "action": "notify_slack",
        "name": "Test",
        "conditions": {"composite_score_gte": 70},
    }
    accounts = [{"id": 1, "status": "completed", "composite_score": 80}]
    context = {"list_id": 20, "accounts": accounts}

    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[rule]), \
         patch("services.automation.execute_action", new_callable=AsyncMock) as mock_execute:

        await evaluate_rules(user_id=2, trigger_event="list_complete", context=context)

        mock_execute.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_rules_no_matching_accounts():
    """Test evaluate_rules doesn't execute when no accounts match."""
    rule = {
        "id": 3,
        "action": "notify_slack",
        "name": "Test",
        "conditions": {"composite_score_gte": 90},
    }
    accounts = [{"id": 1, "status": "completed", "composite_score": 60}]
    context = {"list_id": 30, "accounts": accounts}

    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[rule]), \
         patch("services.automation.execute_action", new_callable=AsyncMock) as mock_execute:

        await evaluate_rules(user_id=3, trigger_event="list_complete", context=context)

        # Should not execute action
        mock_execute.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_rules_multiple_rules():
    """Test evaluate_rules processes multiple rules."""
    rule1 = {
        "id": 1,
        "action": "notify_slack",
        "name": "Rule 1",
        "conditions": {"composite_score_gte": 70},
    }
    rule2 = {
        "id": 2,
        "action": "write_sequences",
        "name": "Rule 2",
        "conditions": {"composite_score_gte": 80},
    }
    accounts = [{"id": 1, "status": "completed", "composite_score": 85}]
    context = {"list_id": 40, "accounts": accounts}

    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[rule1, rule2]), \
         patch("services.automation.execute_action", new_callable=AsyncMock) as mock_execute:

        await evaluate_rules(user_id=4, trigger_event="list_complete", context=context)

        # Both rules should execute
        assert mock_execute.call_count == 2


@pytest.mark.asyncio
async def test_evaluate_rules_exception_caught():
    """Test evaluate_rules catches and logs exceptions."""
    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, side_effect=RuntimeError("Database error")):
        # Should not raise exception
        await evaluate_rules(user_id=5, trigger_event="list_complete", context={})


@pytest.mark.asyncio
async def test_evaluate_rules_no_conditions():
    """Test evaluate_rules with no conditions matches all completed accounts."""
    rule = {
        "id": 4,
        "action": "notify_slack",
        "name": "Test",
        "conditions": None,
    }
    accounts = [
        {"id": 1, "status": "completed", "composite_score": 80},
        {"id": 2, "status": "pending", "composite_score": 90},
    ]
    context = {"list_id": 50, "accounts": accounts}

    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[rule]), \
         patch("services.automation.execute_action", new_callable=AsyncMock) as mock_execute:

        await evaluate_rules(user_id=6, trigger_event="list_complete", context=context)

        # Should execute with only completed account
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args[0]
        assert len(call_args[3]) == 1
        assert call_args[3][0]["id"] == 1


@pytest.mark.asyncio
async def test_evaluate_rules_empty_accounts_in_context():
    """Test evaluate_rules with empty accounts list."""
    rule = {
        "id": 5,
        "action": "notify_slack",
        "name": "Test",
        "conditions": {},
    }
    context = {"list_id": 60, "accounts": []}

    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[rule]), \
         patch("services.automation.execute_action", new_callable=AsyncMock) as mock_execute:

        await evaluate_rules(user_id=7, trigger_event="list_complete", context=context)

        # Should not execute with no accounts
        mock_execute.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_rules_missing_accounts_key():
    """Test evaluate_rules with missing accounts key in context."""
    rule = {
        "id": 6,
        "action": "notify_slack",
        "name": "Test",
        "conditions": {},
    }
    context = {"list_id": 70}  # No accounts key

    with patch("services.automation.get_enabled_rules", new_callable=AsyncMock, return_value=[rule]), \
         patch("services.automation.execute_action", new_callable=AsyncMock) as mock_execute:

        await evaluate_rules(user_id=8, trigger_event="list_complete", context=context)

        # Should not execute with missing accounts
        mock_execute.assert_not_called()
