"""notifications.py - Slack and Microsoft Teams webhook notifications for job events."""

import logging

import httpx

from database import get_integration

logger = logging.getLogger(__name__)


def format_slack_message(event: str, data: dict) -> dict:
    """Build a Slack Block Kit message for the given event type."""
    if event == "research_complete":
        company = data.get("company_name", data.get("company_url", "Unknown"))
        pain = data.get("pain_score", "N/A")
        composite = data.get("composite_score", "N/A")
        doc_url = data.get("doc_url", "")
        return {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"Research Complete: {company}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Pain Score:* {pain}"},
                    {"type": "mrkdwn", "text": f"*Composite Score:* {composite}"},
                ]},
                *([{"type": "section", "text": {"type": "mrkdwn", "text": f"<{doc_url}|View Report>"}}] if doc_url else []),
            ],
        }

    if event == "list_complete":
        list_name = data.get("list_name", "Unnamed List")
        total = data.get("total_accounts", 0)
        completed = data.get("completed_accounts", 0)
        failed = data.get("failed_accounts", 0)
        list_url = data.get("list_url", "")
        return {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"List Analysis Complete: {list_name}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Total:* {total}"},
                    {"type": "mrkdwn", "text": f"*Completed:* {completed}"},
                    {"type": "mrkdwn", "text": f"*Failed:* {failed}"},
                ]},
                *([{"type": "section", "text": {"type": "mrkdwn", "text": f"<{list_url}|View List>"}}] if list_url else []),
            ],
        }

    if event == "high_pain_alert":
        company = data.get("company_name", data.get("company_url", "Unknown"))
        pain = data.get("pain_score", 0)
        doc_url = data.get("doc_url", "")
        return {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"High Pain Alert: {company} ({pain})"}},
                {"type": "section", "text": {
                    "type": "mrkdwn",
                    "text": f"*{company}* has a pain score of *{pain}* — this account may need immediate attention.",
                }},
                *([{"type": "section", "text": {"type": "mrkdwn", "text": f"<{doc_url}|View Report>"}}] if doc_url else []),
            ],
        }

    if event == "watchlist_significant_change":
        company = data.get("company_name", data.get("company_url", "Unknown"))
        pain = data.get("pain_score", "N/A")
        old_pain = data.get("old_pain_score", "N/A")
        composite = data.get("composite_score", "N/A")
        old_composite = data.get("old_composite_score", "N/A")
        doc_url = data.get("doc_url", "")
        watchlist_url = data.get("watchlist_url", "")
        return {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"Watchlist Alert: {company}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Pain Score:* {old_pain} -> {pain}"},
                    {"type": "mrkdwn", "text": f"*Composite Score:* {old_composite} -> {composite}"},
                ]},
                *([{"type": "section", "text": {"type": "mrkdwn", "text": f"<{doc_url}|View Report> | <{watchlist_url}|View Watchlist>"}}] if doc_url else []),
            ],
        }

    # Fallback
    return {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"Auggie event: *{event}*\n```{data}```"}},
        ],
    }


async def send_slack_notification(webhook_url: str, event: str, data: dict) -> bool:
    """Post a Slack Block Kit message to a webhook URL."""
    message = format_slack_message(event, data)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=message)
            if resp.status_code >= 400:
                logger.warning("Slack notification failed (%s): %s", resp.status_code, resp.text[:200])
                return False
            return True
    except Exception:
        logger.exception("Slack notification error")
        return False


async def send_task_failure_alert(task_id: int, task_type: str, error: str) -> None:
    """Post to the internal Slack webhook when a task exhausts all retries.

    No-op if slack_webhook_url is not configured.
    """
    from config import get_settings
    settings = get_settings()
    url = settings.slack_webhook_url
    if not url:
        return
    message = {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "Task Failed (retries exhausted)"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Task ID:* {task_id}"},
                {"type": "mrkdwn", "text": f"*Type:* {task_type}"},
            ]},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Error:*\n```{error[:1000]}```"}},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=message)
    except Exception:
        logger.exception("Failed to send task failure alert to Slack")


async def validate_webhook_url(url: str) -> bool:
    """Validate a Slack webhook URL by sending a test message."""
    test_message = {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Auggie connected successfully! You'll receive notifications here."}},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=test_message)
            return resp.status_code == 200
    except Exception:
        return False


# =============================================================================
# Microsoft Teams
# =============================================================================

def format_teams_message(event: str, data: dict) -> dict:
    """Build a Teams Adaptive Card message for the given event type."""
    if event == "research_complete":
        company = data.get("company_name", data.get("company_url", "Unknown"))
        pain = data.get("pain_score", "N/A")
        composite = data.get("composite_score", "N/A")
        doc_url = data.get("doc_url", "")
        body = [
            {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": f"Research Complete: {company}"},
            {"type": "ColumnSet", "columns": [
                {"type": "Column", "width": "auto", "items": [
                    {"type": "TextBlock", "text": f"**Pain Score:** {pain}", "wrap": True},
                ]},
                {"type": "Column", "width": "auto", "items": [
                    {"type": "TextBlock", "text": f"**Composite Score:** {composite}", "wrap": True},
                ]},
            ]},
        ]
        actions = [{"type": "Action.OpenUrl", "title": "View Report", "url": doc_url}] if doc_url else []
        return _wrap_adaptive_card(body, actions)

    if event == "list_complete":
        list_name = data.get("list_name", "Unnamed List")
        total = data.get("total_accounts", 0)
        completed = data.get("completed_accounts", 0)
        failed = data.get("failed_accounts", 0)
        list_url = data.get("list_url", "")
        body = [
            {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": f"List Analysis Complete: {list_name}"},
            {"type": "FactSet", "facts": [
                {"title": "Total", "value": str(total)},
                {"title": "Completed", "value": str(completed)},
                {"title": "Failed", "value": str(failed)},
            ]},
        ]
        actions = [{"type": "Action.OpenUrl", "title": "View List", "url": list_url}] if list_url else []
        return _wrap_adaptive_card(body, actions)

    if event == "high_pain_alert":
        company = data.get("company_name", data.get("company_url", "Unknown"))
        pain = data.get("pain_score", 0)
        doc_url = data.get("doc_url", "")
        body = [
            {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": f"High Pain Alert: {company} ({pain})"},
            {"type": "TextBlock", "text": f"**{company}** has a pain score of **{pain}** — this account may need immediate attention.", "wrap": True},
        ]
        actions = [{"type": "Action.OpenUrl", "title": "View Report", "url": doc_url}] if doc_url else []
        return _wrap_adaptive_card(body, actions)

    if event == "watchlist_significant_change":
        company = data.get("company_name", data.get("company_url", "Unknown"))
        pain = data.get("pain_score", "N/A")
        old_pain = data.get("old_pain_score", "N/A")
        composite = data.get("composite_score", "N/A")
        old_composite = data.get("old_composite_score", "N/A")
        doc_url = data.get("doc_url", "")
        body = [
            {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": f"Watchlist Alert: {company}"},
            {"type": "FactSet", "facts": [
                {"title": "Pain Score", "value": f"{old_pain} -> {pain}"},
                {"title": "Composite Score", "value": f"{old_composite} -> {composite}"},
            ]},
        ]
        actions = [{"type": "Action.OpenUrl", "title": "View Report", "url": doc_url}] if doc_url else []
        return _wrap_adaptive_card(body, actions)

    # Fallback
    return _wrap_adaptive_card([
        {"type": "TextBlock", "text": f"Auggie event: **{event}**", "wrap": True},
    ])


def _wrap_adaptive_card(body: list, actions: list | None = None) -> dict:
    """Wrap body elements in a Teams Adaptive Card envelope."""
    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body,
            },
        }],
    }
    if actions:
        card["attachments"][0]["content"]["actions"] = actions
    return card


async def send_teams_notification(webhook_url: str, event: str, data: dict) -> bool:
    """Post an Adaptive Card message to a Teams webhook URL."""
    message = format_teams_message(event, data)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=message)
            if resp.status_code >= 400:
                logger.warning("Teams notification failed (%s): %s", resp.status_code, resp.text[:200])
                return False
            return True
    except Exception:
        logger.exception("Teams notification error")
        return False


async def validate_teams_webhook_url(url: str) -> bool:
    """Validate a Teams webhook URL by sending a test message."""
    test_message = _wrap_adaptive_card([
        {"type": "TextBlock", "text": "Auggie connected successfully! You'll receive notifications here.", "wrap": True},
    ])
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=test_message)
            return resp.status_code == 200
    except Exception:
        return False
