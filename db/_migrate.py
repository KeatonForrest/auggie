"""Lightweight SQL migration runner."""

import logging
import os
import glob

logger = logging.getLogger(__name__)

# Fixed lock ID for pg_advisory_lock — prevents concurrent migration runs
_MIGRATION_LOCK_ID = 839_271_493


async def run_migrations(conn):
    """Run pending SQL migrations from migrations/ directory.

    Uses pg_advisory_lock to prevent concurrent startups from racing.
    Tracks applied migrations in a _migrations table.
    Called from init_database() after pool creation.
    """
    # Acquire advisory lock to serialize concurrent startups
    await conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_ID)
    try:
        # Create tracking table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                filename TEXT UNIQUE NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Find migration files
        migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
        if not os.path.isdir(migrations_dir):
            return

        files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))

        for filepath in files:
            filename = os.path.basename(filepath)

            # Check if already applied
            applied = await conn.fetchval(
                "SELECT 1 FROM _migrations WHERE filename = $1",
                filename,
            )
            if applied:
                continue

            # Read and execute
            with open(filepath) as f:
                sql = f.read()

            logger.info("Applying migration: %s", filename)
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO _migrations (filename) VALUES ($1)",
                filename,
            )
            logger.info("Migration applied: %s", filename)
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK_ID)
