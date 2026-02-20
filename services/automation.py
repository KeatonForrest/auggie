"""automation.py - Automation rules engine for post-analysis actions."""

import logging

from database import get_enabled_rules, create_automation_run, complete_automation_run

logger = logging.getLogger(__name__)


def filter_by_conditions(accounts: list[dict], conditions: dict) -> list[dict]:
    """Filter accounts by rule conditions.

    Supported condition keys:
      - composite_score_gte: int
      - pain_score_gte: int
      - fit_score_gte: int
      - timing_score_gte: int
    """
    result = []
    for a in accounts:
        if a.get("status") != "completed":
            continue
        match = True
        for key, value in conditions.items():
            if key == "composite_score_gte":
                if (a.get("composite_score") or 0) < value:
                    match = False
            elif key == "pain_score_gte":
                if (a.get("pain_score") or 0) < value:
                    match = False
            elif key == "fit_score_gte":
                if (a.get("fit_score") or 0) < value:
                    match = False
            elif key == "timing_score_gte":
                if (a.get("timing_score") or 0) < value:
                    match = False
        if match:
            result.append(a)
    return result


async def execute_action(rule: dict, user_id: int, list_id: int, accounts: list[dict]):
    """Dispatch action based on rule configuration. Creates an audit run record."""
    action = rule["action"]
    config = rule.get("action_config") or {}

    run = await create_automation_run(rule["id"], user_id, list_id, len(accounts))

    try:
        if action == "push_instantly":
            raise RuntimeError("Instantly integration has been deprecated")
        elif action == "push_smartlead":
            raise RuntimeError("Smartlead integration has been deprecated")
        elif action == "push_outreach":
            raise RuntimeError("Outreach integration has been deprecated")
        elif action == "push_salesloft":
            raise RuntimeError("SalesLoft integration has been deprecated")
        elif action == "enrich_contacts":
            await _action_enrich_contacts(rule, user_id, list_id, accounts)
        elif action == "write_sequences":
            await _action_write_sequences(rule, user_id, list_id, accounts)
        elif action == "notify_slack":
            await _action_notify_slack(rule, user_id, list_id, accounts, config)
        else:
            await complete_automation_run(run["id"], "failed", f"Unknown action: {action}")
            return

        await complete_automation_run(run["id"], "completed")
    except Exception as e:
        logger.exception("Automation rule %s action failed", rule["id"])
        await complete_automation_run(run["id"], "failed", str(e)[:500])


async def _action_enrich_contacts(rule, user_id, list_id, accounts):
    from api.jobs import run_batch_enrich
    account_ids = [a["id"] for a in accounts]
    await run_batch_enrich(list_id, user_id, account_ids=account_ids)
    logger.info("Automation rule %s: enriched contacts for %d accounts", rule["id"], len(accounts))


async def _action_write_sequences(rule, user_id, list_id, accounts):
    from api.jobs import run_batch_write_sequences
    account_ids = [a["id"] for a in accounts]
    await run_batch_write_sequences(list_id, user_id, account_ids=account_ids)
    logger.info("Automation rule %s: wrote sequences for %d accounts", rule["id"], len(accounts))


async def _action_notify_slack(rule, user_id, list_id, accounts, config):
    from services.notifications import send_slack_notification, send_teams_notification
    from database import get_integration
    from config import get_settings

    slack = await get_integration(user_id, "slack")
    teams = await get_integration(user_id, "teams")
    if not slack and not teams:
        raise RuntimeError("No notification channel connected (Slack or Teams)")

    settings = get_settings()
    notify_data = {
        "list_name": f"Automation: {rule['name']}",
        "total_accounts": len(accounts),
        "completed_accounts": len(accounts),
        "failed_accounts": 0,
        "list_url": f"{settings.app_url}/lists/{list_id}",
    }
    if slack:
        await send_slack_notification(slack["access_token"], "list_complete", notify_data)
    if teams:
        await send_teams_notification(teams["access_token"], "list_complete", notify_data)
    logger.info("Automation rule %s: sent notification", rule["id"])


async def evaluate_rules(user_id: int, trigger_event: str, context: dict):
    """Evaluate automation rules for a given trigger event.

    context: {list_id: int, accounts: [{id, composite_score, pain_score, ...}]}
    """
    try:
        rules = await get_enabled_rules(user_id, trigger_event)
        if not rules:
            return

        for rule in rules:
            conditions = rule.get("conditions") or {}
            if isinstance(conditions, str):
                import json
                conditions = json.loads(conditions)

            matching = filter_by_conditions(context.get("accounts", []), conditions)
            if matching:
                await execute_action(rule, user_id, context["list_id"], matching)
    except Exception:
        logger.exception("Error evaluating automation rules for user %s, event %s", user_id, trigger_event)
