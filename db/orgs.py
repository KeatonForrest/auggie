"""Organization database operations."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import db._pool as _db


async def get_org(org_id: int) -> Optional[dict]:
    """Get an organization by ID."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM organizations WHERE id = $1", org_id)
        return dict(row) if row else None


async def update_org_name(org_id: int, name: str) -> dict:
    """Update org name."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE organizations SET name = $2 WHERE id = $1 RETURNING *",
            org_id, name
        )
        return dict(row)


async def update_org_stripe(org_id: int, stripe_customer_id: str) -> None:
    """Set Stripe customer ID on an org."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE organizations SET stripe_customer_id = $2 WHERE id = $1",
            org_id, stripe_customer_id
        )


async def get_org_members(org_id: int) -> list[dict]:
    """Get all members of an org with user details."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.id, u.email, u.name, u.picture, om.role, om.joined_at
            FROM org_members om
            JOIN users u ON u.id = om.user_id
            WHERE om.org_id = $1
            ORDER BY om.joined_at
            """,
            org_id
        )
        return [dict(row) for row in rows]


async def update_member_role(org_id: int, user_id: int, role: str) -> bool:
    """Change a member's role. Returns True if updated."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE org_members SET role = $3 WHERE org_id = $1 AND user_id = $2",
            org_id, user_id, role
        )
        return result == "UPDATE 1"


async def remove_org_member(org_id: int, user_id: int) -> bool:
    """Remove a member from an org. Returns True if removed."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM org_members WHERE org_id = $1 AND user_id = $2",
            org_id, user_id
        )
        return result == "DELETE 1"


async def create_org_invite(org_id: int, email: str, role: str, invited_by: int) -> dict:
    """Create an invite to join an org. Returns the invite record."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    async with _db._pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO org_invites (org_id, email, role, token, invited_by, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (org_id, email) DO UPDATE SET
                    role = EXCLUDED.role,
                    token = EXCLUDED.token,
                    invited_by = EXCLUDED.invited_by,
                    expires_at = EXCLUDED.expires_at,
                    accepted_at = NULL,
                    created_at = NOW()
                RETURNING *
                """,
                org_id, email, role, token, invited_by, expires_at
            )
            return dict(row)
        except Exception as e:
            raise e


async def get_pending_invites(org_id: int) -> list[dict]:
    """Get pending (unaccepted, unexpired) invites for an org."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT oi.*, u.name AS invited_by_name
            FROM org_invites oi
            JOIN users u ON u.id = oi.invited_by
            WHERE oi.org_id = $1 AND oi.accepted_at IS NULL AND oi.expires_at > NOW()
            ORDER BY oi.created_at DESC
            """,
            org_id
        )
        return [dict(row) for row in rows]


async def get_invite_by_token(token: str) -> Optional[dict]:
    """Get an invite by token (with org name)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT oi.*, o.name AS org_name
            FROM org_invites oi
            JOIN organizations o ON o.id = oi.org_id
            WHERE oi.token = $1
            """,
            token
        )
        return dict(row) if row else None


async def accept_invite(token: str, user_id: int) -> Optional[dict]:
    """Accept an invite. Returns the invite record or None if invalid/expired."""
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            invite = await conn.fetchrow(
                """
                SELECT * FROM org_invites
                WHERE token = $1 AND accepted_at IS NULL AND expires_at > NOW()
                FOR UPDATE
                """,
                token
            )
            if not invite:
                return None

            # Mark invite as accepted
            await conn.execute(
                "UPDATE org_invites SET accepted_at = NOW() WHERE id = $1",
                invite["id"]
            )

            # Add user to org
            await conn.execute(
                """
                INSERT INTO org_members (org_id, user_id, role)
                VALUES ($1, $2, $3)
                ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                invite["org_id"], user_id, invite["role"]
            )

            # Update user's org_id
            await conn.execute(
                "UPDATE users SET org_id = $2 WHERE id = $1",
                user_id, invite["org_id"]
            )

            return dict(invite)


async def revoke_invite(invite_id: int, org_id: int) -> bool:
    """Revoke a pending invite. Returns True if deleted."""
    async with _db._pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM org_invites WHERE id = $1 AND org_id = $2 AND accepted_at IS NULL",
            invite_id, org_id
        )
        return result == "DELETE 1"


async def get_pending_invites_for_email(email: str) -> list[dict]:
    """Get pending invites for an email address."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT oi.*, o.name AS org_name
            FROM org_invites oi
            JOIN organizations o ON o.id = oi.org_id
            WHERE oi.email = $1 AND oi.accepted_at IS NULL AND oi.expires_at > NOW()
            ORDER BY oi.created_at DESC
            """,
            email
        )
        return [dict(row) for row in rows]


async def get_org_documents(org_id: int, limit: int = 50) -> list[dict]:
    """Get all research documents across an org (for admin view)."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT rd.id, rd.company_url, rd.company_name, rd.created_at,
                   rd.opportunity_score, rd.pain_score, rd.fit_score, rd.timing_score,
                   u.name AS researcher_name, u.email AS researcher_email
            FROM research_documents rd
            JOIN users u ON u.id = rd.user_id
            WHERE u.org_id = $1
            ORDER BY rd.created_at DESC
            LIMIT $2
            """,
            org_id, limit
        )
        return [dict(row) for row in rows]


async def get_org_usage_breakdown(org_id: int, days: int = 30) -> list[dict]:
    """Get per-member usage breakdown for an org."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.id, u.name, u.email, u.picture, om.role,
                   COUNT(rd.id) AS research_count,
                   MAX(rd.created_at) AS last_activity
            FROM org_members om
            JOIN users u ON u.id = om.user_id
            LEFT JOIN research_documents rd ON rd.user_id = u.id
                AND rd.created_at > NOW() - make_interval(days => $2)
            WHERE om.org_id = $1
            GROUP BY u.id, u.name, u.email, u.picture, om.role
            ORDER BY research_count DESC
            """,
            org_id, days
        )
        return [dict(row) for row in rows]


async def user_has_data(user_id: int) -> bool:
    """Check if a user has any research data (documents, lists, etc)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT EXISTS(SELECT 1 FROM research_documents WHERE user_id = $1) AS has_data",
            user_id
        )
        return row["has_data"]


async def delete_empty_org(org_id: int) -> bool:
    """Delete an org if it has no members. Returns True if deleted."""
    async with _db._pool.acquire() as conn:
        member_count = await conn.fetchval(
            "SELECT COUNT(*) FROM org_members WHERE org_id = $1", org_id
        )
        if member_count == 0:
            await conn.execute("DELETE FROM organizations WHERE id = $1", org_id)
            return True
        return False
