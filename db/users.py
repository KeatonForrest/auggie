"""User database operations."""

import asyncpg
from typing import Optional
from cachetools import TTLCache

import db._pool as _db

# 256 users, 30s TTL — avoids hitting DB on every page load / credit check
_usage_cache: TTLCache = TTLCache(maxsize=256, ttl=30)


def _invalidate_usage_cache(user_id: int) -> None:
    """Remove cached usage so next call fetches fresh data."""
    _usage_cache.pop(user_id, None)


async def get_user_by_google_id(google_id: str) -> Optional[dict]:
    """Get a user by their Google ID."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, org_id FROM users WHERE google_id = $1",
            google_id
        )
        return dict(row) if row else None


async def get_user_by_microsoft_id(microsoft_id: str) -> Optional[dict]:
    """Get a user by their Microsoft ID."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, org_id FROM users WHERE microsoft_id = $1",
            microsoft_id
        )
        return dict(row) if row else None


async def get_user_by_id(user_id: int) -> Optional[dict]:
    """Get a user by their ID, including org context."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.*,
                   om.role AS org_role,
                   o.name AS org_name,
                   o.slug AS org_slug,
                   o.bonus_credits AS org_credits,
                   o.stripe_customer_id AS org_stripe_customer_id
            FROM users u
            LEFT JOIN org_members om ON om.user_id = u.id
            LEFT JOIN organizations o ON o.id = u.org_id
            WHERE u.id = $1
            """,
            user_id
        )
        return dict(row) if row else None


async def create_user(email: str, name: str, picture: str, google_id: str) -> dict:
    """Create a new user from Google OAuth data with auto-created org."""
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, name, picture, google_id, bonus_credits)
                VALUES ($1, $2, $3, $4, 0)
                RETURNING *
                """,
                email, name, picture, google_id
            )
            user = dict(row)
            # Auto-create a 1-person org (org holds the credits)
            org_name = name or email
            org_slug = f"user-{user['id']}"
            org_row = await conn.fetchrow(
                """
                INSERT INTO organizations (name, slug, bonus_credits)
                VALUES ($1, $2, 1000)
                RETURNING id
                """,
                org_name, org_slug
            )
            org_id = org_row["id"]
            await conn.execute(
                "UPDATE users SET org_id = $2 WHERE id = $1",
                user["id"], org_id
            )
            await conn.execute(
                "INSERT INTO org_members (org_id, user_id, role) VALUES ($1, $2, 'admin')",
                org_id, user["id"]
            )
            user["org_id"] = org_id
            user["org_role"] = "admin"
            user["org_name"] = org_name
            user["org_slug"] = org_slug
            user["org_credits"] = 1000
            user["org_stripe_customer_id"] = None
            return user


async def create_user_microsoft(email: str, name: str, picture: str, microsoft_id: str) -> dict:
    """Create a new user from Microsoft OAuth data with auto-created org."""
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, name, picture, microsoft_id, bonus_credits)
                VALUES ($1, $2, $3, $4, 0)
                RETURNING *
                """,
                email, name, picture, microsoft_id
            )
            user = dict(row)
            org_name = name or email
            org_slug = f"user-{user['id']}"
            org_row = await conn.fetchrow(
                """
                INSERT INTO organizations (name, slug, bonus_credits)
                VALUES ($1, $2, 1000)
                RETURNING id
                """,
                org_name, org_slug
            )
            org_id = org_row["id"]
            await conn.execute(
                "UPDATE users SET org_id = $2 WHERE id = $1",
                user["id"], org_id
            )
            await conn.execute(
                "INSERT INTO org_members (org_id, user_id, role) VALUES ($1, $2, 'admin')",
                org_id, user["id"]
            )
            user["org_id"] = org_id
            user["org_role"] = "admin"
            user["org_name"] = org_name
            user["org_slug"] = org_slug
            user["org_credits"] = 1000
            user["org_stripe_customer_id"] = None
            return user


async def update_user_profile(
    user_id: int,
    company_name: str,
    product_name: str,
    product_description: str,
    problems_solved: str,
    differentiators: str,
    target_company_size: str,
    target_industries: str,
    target_personas: str,
    competitors: str,
    product_type: str = "saas",
    custom_signals: str = "",
) -> dict:
    """Update user's onboarding profile with enhanced fields."""
    # Build a rich product_context string for Claude
    product_context = build_product_context(
        product_name=product_name,
        product_description=product_description,
        problems_solved=problems_solved,
        differentiators=differentiators,
        target_company_size=target_company_size,
        target_industries=target_industries,
        target_personas=target_personas,
        competitors=competitors,
        product_type=product_type,
        custom_signals=custom_signals,
    )

    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET company_name = $2,
                product_context = $3,
                product_name = $4,
                product_description = $5,
                problems_solved = $6,
                differentiators = $7,
                target_company_size = $8,
                target_industries = $9,
                target_personas = $10,
                competitors = $11,
                product_type = $12,
                custom_signals = $13
            WHERE id = $1
            RETURNING *
            """,
            user_id, company_name, product_context,
            product_name, product_description, problems_solved, differentiators,
            target_company_size, target_industries, target_personas, competitors,
            product_type, custom_signals
        )
        # Invalidate auth cache so the next request sees updated profile
        from auth_cache import invalidate_user_cache
        invalidate_user_cache(user_id)
        return dict(row)


def build_product_context(
    product_name: str,
    product_description: str,
    problems_solved: str,
    differentiators: str,
    target_company_size: str,
    target_industries: str,
    target_personas: str,
    competitors: str,
    product_type: str = "saas",
    custom_signals: str = "",
) -> str:
    """Build a rich product context string for Claude from onboarding data.

    Note: In v2, many fields may be empty as they're extracted from uploaded
    materials instead. The core required field is problems_solved.
    """
    parts = []

    if product_name:
        parts.append(f"**Product:** {product_name}")

    if product_description:
        parts.append(f"**What it does:** {product_description}")

    if problems_solved:
        parts.append(f"**Problems it solves:** {problems_solved}")

    if differentiators:
        parts.append(f"**Key differentiators:** {differentiators}")

    if target_company_size:
        parts.append(f"**Target company size:** {target_company_size}")

    if target_industries:
        parts.append(f"**Target industries:** {target_industries}")

    if target_personas:
        parts.append(f"**Target personas:** {target_personas}")

    if competitors:
        parts.append(f"**Competitors:** {competitors}")

    if product_type and product_type != "saas":
        parts.append(f"**Product type:** {product_type}")

    if custom_signals:
        parts.append(f"**Custom signals:** {custom_signals}")

    # Ensure we always return something
    if not parts:
        parts.append("(Product details to be extracted from uploaded materials)")

    return "\n".join(parts)


async def update_user_stripe(
    user_id: int,
    stripe_customer_id: str,
    stripe_subscription_id: str = None,
    subscription_status: str = 'none'
) -> dict:
    """Update user's Stripe billing info."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET stripe_customer_id = $2,
                stripe_subscription_id = $3,
                subscription_status = $4
            WHERE id = $1
            RETURNING *
            """,
            user_id, stripe_customer_id, stripe_subscription_id, subscription_status
        )
        return dict(row)


async def get_user_usage(user_id: int) -> dict:
    """Get user's current usage stats (credits from org). Cached for 30s."""
    cached = _usage_cache.get(user_id)
    if cached is not None:
        return cached
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.searches_used, COALESCE(o.bonus_credits, u.bonus_credits) AS bonus_credits,
                   u.billing_period_start, u.subscription_status, u.is_admin
            FROM users u
            LEFT JOIN organizations o ON o.id = u.org_id
            WHERE u.id = $1
            """,
            user_id
        )
        result = dict(row) if row else None
        if result is not None:
            _usage_cache[user_id] = result
        return result


async def add_credits(user_id: int, credits: int) -> int:
    """Add credits to user's org. Credits are in whole units (1 credit = 100 cents internally).
    Returns new total in cents."""
    cents = credits * 100
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE organizations
            SET bonus_credits = bonus_credits + $2
            WHERE id = (SELECT org_id FROM users WHERE id = $1)
            RETURNING bonus_credits
            """,
            user_id, cents
        )
        _invalidate_usage_cache(user_id)
        return row['bonus_credits']


async def use_credit(user_id: int, cents: int = 100) -> bool:
    """Use credits from user's org pool. Default 100 cents (1 credit). Enrichment = 50 cents.
    Returns True if successful, False if insufficient credits."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE organizations
            SET bonus_credits = bonus_credits - $2
            WHERE id = (SELECT org_id FROM users WHERE id = $1) AND bonus_credits >= $2
            RETURNING bonus_credits
            """,
            user_id, cents
        )
        _invalidate_usage_cache(user_id)
        return row is not None


async def refund_credit(user_id: int, cents: int = 100) -> None:
    """Refund credits to user's org pool (e.g. when a reserved job fails)."""
    async with _db._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE organizations SET bonus_credits = bonus_credits + $2
            WHERE id = (SELECT org_id FROM users WHERE id = $1)
            """,
            user_id, cents
        )
        _invalidate_usage_cache(user_id)


async def fulfill_session(session_id: str, user_id: int, credits: int) -> bool:
    """Idempotently fulfill a Stripe checkout session.

    Inserts into fulfilled_sessions and adds credits to the user's org in one transaction.
    Returns True if credits were added, False if already fulfilled.
    """
    cents = credits * 100
    async with _db._pool.acquire() as conn:
        async with conn.transaction():
            org_id = await conn.fetchval("SELECT org_id FROM users WHERE id = $1", user_id)
            try:
                await conn.execute(
                    "INSERT INTO fulfilled_sessions (session_id, user_id, credits, org_id) VALUES ($1, $2, $3, $4)",
                    session_id, user_id, credits, org_id,
                )
            except asyncpg.exceptions.UniqueViolationError:
                return False
            await conn.execute(
                "UPDATE organizations SET bonus_credits = bonus_credits + $2 WHERE id = $1",
                org_id, cents,
            )
            return True


async def try_start_list_analysis(list_id: int) -> bool:
    """Atomically transition a list to 'analyzing' status.

    Returns True if the transition succeeded, False if already analyzing.
    """
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE lists SET status = 'analyzing', updated_at = NOW() WHERE id = $1 AND status != 'analyzing' RETURNING id",
            list_id,
        )
        return row is not None


async def list_all_users_admin(limit: int = 50, offset: int = 0, search: str = None) -> list[dict]:
    """List all users with org info for admin dashboard."""
    async with _db._pool.acquire() as conn:
        if search:
            rows = await conn.fetch(
                """
                SELECT u.id, u.email, u.name, u.is_admin, u.created_at,
                       o.name AS org_name, o.bonus_credits,
                       (SELECT count(*) FROM research_documents rd WHERE rd.user_id = u.id) AS doc_count,
                       (SELECT count(*) FROM lists l WHERE l.user_id = u.id) AS list_count
                FROM users u
                LEFT JOIN organizations o ON o.id = u.org_id
                WHERE u.email ILIKE $3 OR u.name ILIKE $3
                ORDER BY u.created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit, offset, f"%{search}%"
            )
        else:
            rows = await conn.fetch(
                """
                SELECT u.id, u.email, u.name, u.is_admin, u.created_at,
                       o.name AS org_name, o.bonus_credits,
                       (SELECT count(*) FROM research_documents rd WHERE rd.user_id = u.id) AS doc_count,
                       (SELECT count(*) FROM lists l WHERE l.user_id = u.id) AS list_count
                FROM users u
                LEFT JOIN organizations o ON o.id = u.org_id
                ORDER BY u.created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit, offset
            )
        return [dict(row) for row in rows]


async def toggle_admin(user_id: int) -> bool:
    """Toggle is_admin flag for a user. Returns new value."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE users SET is_admin = NOT is_admin WHERE id = $1 RETURNING is_admin",
            user_id
        )
        return row["is_admin"] if row else False


