"""database pool and schema initialization."""

import logging
import asyncpg
from typing import Optional
from contextlib import asynccontextmanager

from config import get_settings
from db._migrate import run_migrations

logger = logging.getLogger(__name__)

# Connection pool (initialized on startup)
_pool: Optional[asyncpg.Pool] = None


async def init_database():
    """Initialize connection pool, run migrations, and clean up stale jobs."""
    global _pool
    settings = get_settings()

    async def _init_connection(conn):
        await conn.execute(f"SET statement_timeout = '{settings.db_statement_timeout}s'")

    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        statement_cache_size=100,
        timeout=settings.db_pool_acquire_timeout,
        init=_init_connection,
    )

    async with _pool.acquire() as conn:
        # Disable statement_timeout for schema setup (DDL + migrations can be slow)
        await conn.execute("SET statement_timeout = 0")

        # Enable pgvector extension before migrations (001 references vector type)
        if settings.materials_enabled:
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except asyncpg.exceptions.FeatureNotSupportedError:
                logger.warning("pgvector extension not available. Materials feature will not work. Install pgvector on your PostgreSQL server.")

        # Run SQL migrations (all schema DDL lives in migrations/)
        await run_migrations(conn)

        # Mark stale processing jobs as failed (covers Railway redeploys)
        await conn.execute("""
            UPDATE research_jobs
            SET status = 'failed', error_message = 'Server restarted during processing', completed_at = NOW()
            WHERE status = 'processing' AND created_at < NOW() - INTERVAL '10 minutes'
        """)

        # Mark stale bulk jobs as failed
        await conn.execute("""
            UPDATE bulk_jobs SET status = 'failed', completed_at = NOW()
            WHERE status = 'processing' AND created_at < NOW() - INTERVAL '30 minutes'
        """)

        # Mark stale analyzing lists as failed
        await conn.execute("""
            UPDATE lists SET status = 'failed', updated_at = NOW()
            WHERE status = 'analyzing' AND created_at < NOW() - INTERVAL '30 minutes'
        """)

        # Migrate existing users to 1-person orgs (one txn per user, with row lock)
        unmigrated_ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM users WHERE org_id IS NULL"
        )]
        for uid in unmigrated_ids:
            async with conn.transaction():
                u = await conn.fetchrow(
                    "SELECT id, email, name, company_name, stripe_customer_id, bonus_credits "
                    "FROM users WHERE id = $1 AND org_id IS NULL FOR UPDATE",
                    uid
                )
                if not u:
                    continue  # Already migrated by another instance

                org_name = u["company_name"] or u["name"] or u["email"]
                org_slug = f"user-{u['id']}"
                try:
                    org_row = await conn.fetchrow(
                        """
                        INSERT INTO organizations (name, slug, stripe_customer_id, bonus_credits)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id
                        """,
                        org_name, org_slug, u["stripe_customer_id"], u["bonus_credits"]
                    )
                    org_id = org_row["id"]
                    await conn.execute(
                        "UPDATE users SET org_id = $2, bonus_credits = 0 WHERE id = $1",
                        u["id"], org_id
                    )
                    await conn.execute(
                        """
                        INSERT INTO org_members (org_id, user_id, role)
                        VALUES ($1, $2, 'admin')
                        ON CONFLICT (org_id, user_id) DO NOTHING
                        """,
                        org_id, u["id"]
                    )
                    # Backfill org_id on shared tables
                    for table in ["materials", "material_chunks", "lists", "webhooks"]:
                        try:
                            await conn.execute(
                                f"UPDATE {table} SET org_id = $2 WHERE user_id = $1 AND org_id IS NULL",
                                u["id"], org_id
                            )
                        except Exception:
                            pass
                except asyncpg.exceptions.UniqueViolationError:
                    # Slug conflict — another instance created it; adopt the existing org
                    existing_org = await conn.fetchval(
                        "SELECT id FROM organizations WHERE slug = $1", org_slug
                    )
                    if existing_org:
                        await conn.execute(
                            "UPDATE users SET org_id = $2, bonus_credits = 0 WHERE id = $1",
                            u["id"], existing_org
                        )
                        await conn.execute(
                            """
                            INSERT INTO org_members (org_id, user_id, role)
                            VALUES ($1, $2, 'admin')
                            ON CONFLICT (org_id, user_id) DO NOTHING
                            """,
                            existing_org, u["id"]
                        )


async def close_database():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_connection():
    """Get a connection from the pool."""
    async with _pool.acquire() as conn:
        yield conn
