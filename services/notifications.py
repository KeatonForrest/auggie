"""notifications.py - Slack webhook notifications for job events."""

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
