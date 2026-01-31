"""Automation rules and runs database operations."""

import json

import db._pool as _db


async def create_automation_rule(user_id: int, name: str, trigger_event: str, conditions: dict, action: str, action_config: dict) -> dict:
    """Create an automation rule."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO automation_rules (user_id, name, trigger_event, conditions, action, action_config)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
            RETURNING *
            """,
            user_id, name, trigger_event, json.dumps(conditions), action, json.dumps(action_config),
        )
        return dict(row)


async def get_automation_rules(user_id: int) -> list[dict]:
    """Get all automation rules for a user."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM automation_rules WHERE user_id = $1 ORDER BY created_at DESC",
            user_id,
        )
        return [dict(row) for row in rows]


async def update_automation_rule(rule_id: int, user_id: int, **fields) -> dict | None:
    """Update an automation rule. Only updates provided fields."""
    allowed = {"name", "trigger_event", "conditions", "action", "action_config", "enabled"}
    updates = []
    params = []
    idx = 3
    for key, val in fields.items():
        if key not in allowed or val is None:
            continue
        if key in ("conditions", "action_config"):
            updates.append(f"{key} = ${idx}::jsonb")
            params.append(json.dumps(val))
        else:
            updates.append(f"{key} = ${idx}")
            params.append(val)
        idx += 1

    if not updates:
        return None

    query = f"UPDATE automation_rules SET {', '.join(updates)} WHERE id = $1 AND user_id = $2 RETURNING *"
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(query, rule_id, user_id, *params)
        return dict(row) if row else None


async def delete_automation_rule(rule_id: int, user_id: int) -> bool:
    """Delete an automation rule."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM automation_rules WHERE id = $1 AND user_id = $2",
            rule_id, user_id,
        )
        return result == "DELETE 1"


async def get_enabled_rules(user_id: int, trigger_event: str) -> list[dict]:
    """Get enabled automation rules for a user and trigger event."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM automation_rules WHERE user_id = $1 AND trigger_event = $2 AND enabled = TRUE ORDER BY id",
            user_id, trigger_event,
        )
        return [dict(row) for row in rows]


async def create_automation_run(rule_id: int, user_id: int, list_id: int, matched_accounts: int) -> dict:
    """Create an automation run audit record."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO automation_runs (rule_id, user_id, list_id, matched_accounts)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            rule_id, user_id, list_id, matched_accounts,
        )
        return dict(row)


async def complete_automation_run(run_id: int, status: str, error_message: str = None) -> None:
    """Mark an automation run as completed or failed."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE automation_runs
            SET status = $2, error_message = $3, completed_at = NOW()
            WHERE id = $1
            """,
            run_id, status, error_message,
        )


async def get_automation_runs(user_id: int, rule_id: int = None, limit: int = 20) -> list[dict]:
    """Get recent automation runs, optionally filtered by rule."""
    async with _db._pool.acquire() as conn:
        if rule_id:
            rows = await conn.fetch(
                """
                SELECT ar.*, au.name AS rule_name
                FROM automation_runs ar
                JOIN automation_rules au ON au.id = ar.rule_id
                WHERE ar.user_id = $1 AND ar.rule_id = $2
                ORDER BY ar.created_at DESC LIMIT $3
                """,
                user_id, rule_id, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT ar.*, au.name AS rule_name
                FROM automation_runs ar
                JOIN automation_rules au ON au.id = ar.rule_id
                WHERE ar.user_id = $1
                ORDER BY ar.created_at DESC LIMIT $2
                """,
                user_id, limit,
            )
        return [dict(row) for row in rows]
