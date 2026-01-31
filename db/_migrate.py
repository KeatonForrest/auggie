"""Lightweight SQL migration runner."""

import logging
import os
import glob

logger = logging.getLogger(__name__)


async def run_migrations(conn):
    """Run pending SQL migrations from migrations/ directory.

    Tracks applied migrations in a _migrations table.
    Called from init_database() after pool creation.
    """
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
