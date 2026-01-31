"""database pool and schema initialization."""

import logging
import asyncpg
import secrets
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from contextlib import asynccontextmanager

from config import get_settings

logger = logging.getLogger(__name__)

# Connection pool (initialized on startup)
_pool: Optional[asyncpg.Pool] = None


async def init_database():
    """Initialize connection pool and create tables if they don't exist."""
    global _pool
    settings = get_settings()

    async def _init_connection(conn):
        await conn.execute(f"SET statement_timeout = '{settings.db_statement_timeout}s'")

    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        statement_cache_size=0,  # Disable cache to handle schema changes
        timeout=settings.db_pool_acquire_timeout,
        init=_init_connection,
    )

    async with _pool.acquire() as conn:
        # Disable statement_timeout for schema setup (DDL + migrations can be slow)
        await conn.execute("SET statement_timeout = 0")

        # Enable pgvector extension for materials feature (only if enabled)
        if settings.materials_enabled:
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except asyncpg.exceptions.FeatureNotSupportedError:
                logger.warning("pgvector extension not available. Materials feature will not work. Install pgvector on your PostgreSQL server.")
        # Create users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,

                -- Auth
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                picture TEXT,
                google_id TEXT UNIQUE,
                microsoft_id TEXT UNIQUE,

                -- Profile (legacy - kept for backwards compatibility)
                company_name TEXT,
                product_context TEXT,
                industry TEXT,

                -- Enhanced Profile - Product Info
                product_name TEXT,
                product_description TEXT,
                problems_solved TEXT,
                differentiators TEXT,

                -- Enhanced Profile - ICP
                target_company_size TEXT,
                target_industries TEXT,
                target_personas TEXT,

                -- Enhanced Profile - Competition
                competitors TEXT,

                -- Billing
                stripe_customer_id TEXT UNIQUE,
                stripe_subscription_id TEXT,
                subscription_status TEXT DEFAULT 'none'
                    CHECK (subscription_status IN ('none', 'active', 'past_due', 'canceled')),

                -- Usage
                searches_used INTEGER DEFAULT 0,
                bonus_credits INTEGER DEFAULT 0,
                billing_period_start TIMESTAMPTZ DEFAULT NOW(),

                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Add new columns if they don't exist (for existing databases)
        new_columns = [
            ("product_name", "TEXT"),
            ("product_description", "TEXT"),
            ("problems_solved", "TEXT"),
            ("differentiators", "TEXT"),
            ("target_company_size", "TEXT"),
            ("target_industries", "TEXT"),
            ("target_personas", "TEXT"),
            ("competitors", "TEXT"),
        ]
        for col_name, col_type in new_columns:
            try:
                await conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            except asyncpg.exceptions.DuplicateColumnError:
                pass  # Column already exists

        # Add bonus_credits column if it doesn't exist
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN bonus_credits INTEGER DEFAULT 0")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Migrate bonus_credits to cents (1 credit = 100 cents)
        # Only runs once: if any user has credits between 1-999, they're still in old format
        try:
            await conn.execute("""
                UPDATE users SET bonus_credits = bonus_credits * 100
                WHERE bonus_credits > 0 AND bonus_credits < 100
            """)
        except Exception:
            pass

        # Add microsoft_id column for Microsoft OAuth (MSP customers)
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN microsoft_id TEXT UNIQUE")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Add is_admin column for unlimited usage
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Add product_type column (saas or msp)
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN product_type TEXT DEFAULT 'saas'")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Make google_id nullable (for users who sign up with Microsoft only)
        try:
            await conn.execute("ALTER TABLE users ALTER COLUMN google_id DROP NOT NULL")
        except Exception:
            pass  # Already nullable or column doesn't exist

        # Create research_documents table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS research_documents (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

                company_url TEXT NOT NULL,
                company_name TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),

                company_overview TEXT,
                projects_initiatives TEXT,
                confirmed_tech_stack TEXT,
                hiring_signals TEXT,
                business_problems TEXT,
                product_fit TEXT,
                talking_points TEXT,
                recent_news TEXT,
                information_gaps TEXT,
                full_markdown TEXT
            )
        """)

        # Add recent_news column if it doesn't exist (for existing databases)
        try:
            await conn.execute("ALTER TABLE research_documents ADD COLUMN recent_news TEXT")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Add key_contacts column if it doesn't exist (for existing databases)
        try:
            await conn.execute("ALTER TABLE research_documents ADD COLUMN key_contacts TEXT")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Add existential_data_points column if it doesn't exist (for existing databases)
        try:
            await conn.execute("ALTER TABLE research_documents ADD COLUMN existential_data_points TEXT")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Add opportunity scoring columns
        score_columns = [
            ("opportunity_score", "INTEGER"),
            ("pain_score", "INTEGER"),
            ("fit_score", "INTEGER"),
            ("timing_score", "INTEGER"),
            ("score_summary", "TEXT"),
            ("pain_evidence", "TEXT"),
            ("fit_evidence", "TEXT"),
            ("timing_evidence", "TEXT"),
        ]
        for col_name, col_type in score_columns:
            try:
                await conn.execute(f"ALTER TABLE research_documents ADD COLUMN {col_name} {col_type}")
            except asyncpg.exceptions.DuplicateColumnError:
                pass

        # Add thinking_content and model_used columns
        for col_name, col_type in [("thinking_content", "TEXT"), ("model_used", "TEXT")]:
            try:
                await conn.execute(f"ALTER TABLE research_documents ADD COLUMN {col_name} {col_type}")
            except asyncpg.exceptions.DuplicateColumnError:
                pass

        # Create research_feedback table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS research_feedback (
                id BIGSERIAL PRIMARY KEY,
                document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                is_positive BOOLEAN NOT NULL,
                comment TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(document_id, user_id)
            )
        """)

        # Create indexes (IF NOT EXISTS for indexes requires a different approach)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_user_created
            ON research_documents(user_id, created_at DESC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_google_id
            ON users(google_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_stripe_customer
            ON users(stripe_customer_id)
            WHERE stripe_customer_id IS NOT NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_microsoft_id
            ON users(microsoft_id)
            WHERE microsoft_id IS NOT NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_user_url
            ON research_documents(user_id, company_url)
        """)

        # =================================================================
        # API Keys table
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                key_hash TEXT NOT NULL,
                prefix TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT 'Default',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_used_at TIMESTAMPTZ,
                revoked BOOLEAN DEFAULT FALSE
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_user
            ON api_keys(user_id)
            WHERE NOT revoked
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_prefix
            ON api_keys(prefix)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                id BIGSERIAL PRIMARY KEY,
                api_key_id BIGINT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
                endpoint TEXT NOT NULL,
                credits_used INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_usage_key
            ON api_usage(api_key_id, created_at DESC)
        """)

        # Enriched contacts table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS enriched_contacts (
                id BIGSERIAL PRIMARY KEY,
                document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT,
                first_name TEXT,
                last_name TEXT,
                title TEXT,
                email TEXT,
                email_status TEXT,
                profile_url TEXT,
                company_name TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_enriched_contacts_doc
            ON enriched_contacts(document_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_enriched_contacts_user
            ON enriched_contacts(user_id)
        """)

        # =================================================================
        # Research Jobs table (async API)
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS research_jobs (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                api_key_id BIGINT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
                company_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing'
                    CHECK (status IN ('processing', 'completed', 'failed')),
                document_id BIGINT REFERENCES research_documents(id) ON DELETE SET NULL,
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_research_jobs_user
            ON research_jobs(user_id, created_at DESC)
        """)

        # =================================================================
        # Webhooks table (one per user)
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS webhooks (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                secret TEXT NOT NULL,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id)
            )
        """)

        # =================================================================
        # Webhook Deliveries table (audit log)
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id BIGSERIAL PRIMARY KEY,
                webhook_id BIGINT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
                job_id BIGINT NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'success', 'failed')),
                http_status INTEGER,
                error_message TEXT,
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_job
            ON webhook_deliveries(job_id)
        """)

        # Make research_jobs.api_key_id nullable (for web-uploaded lists)
        try:
            await conn.execute("ALTER TABLE research_jobs ALTER COLUMN api_key_id DROP NOT NULL")
        except Exception:
            pass

        # Add progress column for pipeline stage tracking
        try:
            await conn.execute("ALTER TABLE research_jobs ADD COLUMN progress TEXT")
        except Exception:
            pass

        # Mark stale processing jobs as failed (covers Railway redeploys)
        await conn.execute("""
            UPDATE research_jobs
            SET status = 'failed', error_message = 'Server restarted during processing', completed_at = NOW()
            WHERE status = 'processing' AND created_at < NOW() - INTERVAL '10 minutes'
        """)

        # =================================================================
        # Bulk Jobs tables
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bulk_jobs (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                api_key_id BIGINT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
                name TEXT,
                status TEXT NOT NULL DEFAULT 'processing'
                    CHECK (status IN ('processing', 'completed', 'partial_failure', 'failed')),
                total_items INTEGER NOT NULL,
                completed_items INTEGER NOT NULL DEFAULT 0,
                failed_items INTEGER NOT NULL DEFAULT 0,
                credits_reserved INTEGER NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_bulk_jobs_user
            ON bulk_jobs(user_id, created_at DESC)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bulk_job_items (
                id BIGSERIAL PRIMARY KEY,
                bulk_job_id BIGINT NOT NULL REFERENCES bulk_jobs(id) ON DELETE CASCADE,
                research_job_id BIGINT REFERENCES research_jobs(id) ON DELETE SET NULL,
                company_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
                document_id BIGINT REFERENCES research_documents(id) ON DELETE SET NULL,
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_bulk_job_items_bulk
            ON bulk_job_items(bulk_job_id)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_webhooks_user_active
            ON webhooks(user_id)
            WHERE active = TRUE
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_bulk_jobs_status_created
            ON bulk_jobs(status, created_at DESC)
        """)

        # Mark stale bulk jobs as failed
        await conn.execute("""
            UPDATE bulk_jobs SET status = 'failed', completed_at = NOW()
            WHERE status = 'processing' AND created_at < NOW() - INTERVAL '30 minutes'
        """)

        # =================================================================
        # Lists tables
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS lists (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                api_key_id BIGINT,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                total_accounts INTEGER DEFAULT 0,
                analyzed_accounts INTEGER DEFAULT 0,
                failed_accounts INTEGER DEFAULT 0,
                credits_reserved INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_lists_user
            ON lists(user_id, created_at DESC)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS list_accounts (
                id BIGSERIAL PRIMARY KEY,
                list_id BIGINT REFERENCES lists(id) ON DELETE CASCADE,
                company_url TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                document_id BIGINT REFERENCES research_documents(id) ON DELETE SET NULL,
                research_job_id BIGINT REFERENCES research_jobs(id) ON DELETE SET NULL,
                pain_score INTEGER,
                fit_score INTEGER,
                timing_score INTEGER,
                composite_score INTEGER,
                company_name TEXT,
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                analyzed_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_list_accounts_list
            ON list_accounts(list_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_list_accounts_status
            ON list_accounts(status)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_research_jobs_status_created
            ON research_jobs(status, created_at DESC)
        """)

        # =================================================================
        # Task Queue table (durable background jobs)
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id BIGSERIAL PRIMARY KEY,
                task_type TEXT NOT NULL,
                payload JSONB NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INT NOT NULL DEFAULT 0,
                max_attempts INT NOT NULL DEFAULT 3,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                error TEXT,
                claimed_by TEXT
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_queue_pending
            ON task_queue (status, created_at)
            WHERE status = 'pending'
        """)

        # Fulfilled sessions table (idempotent Stripe fulfillment)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS fulfilled_sessions (
                session_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                credits INTEGER NOT NULL,
                fulfilled_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Add org_id to fulfilled_sessions for billing audit
        try:
            await conn.execute("ALTER TABLE fulfilled_sessions ADD COLUMN org_id BIGINT REFERENCES organizations(id)")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_lists_status_created
            ON lists(status, created_at DESC)
        """)

        # Mark stale analyzing lists as failed
        await conn.execute("""
            UPDATE lists SET status = 'failed', updated_at = NOW()
            WHERE status = 'analyzing' AND created_at < NOW() - INTERVAL '30 minutes'
        """)

        # =================================================================
        # Integrations table (HubSpot, Instantly, etc.)
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS integrations (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_expires_at TIMESTAMPTZ,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, provider)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_integrations_user_provider
            ON integrations(user_id, provider)
        """)

        # Add hubspot_source column to lists table for tracking HubSpot-imported lists
        try:
            await conn.execute("ALTER TABLE lists ADD COLUMN source JSONB DEFAULT '{}'")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Add pushed_to column to list_accounts for tracking Instantly pushes
        try:
            await conn.execute("ALTER TABLE list_accounts ADD COLUMN pushed_to JSONB DEFAULT '{}'")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Add pipeline status columns to list_accounts
        for col_name, col_default in [("enrichment_status", "none"), ("outreach_status", "none")]:
            try:
                await conn.execute(f"ALTER TABLE list_accounts ADD COLUMN {col_name} TEXT DEFAULT '{col_default}'")
            except asyncpg.exceptions.DuplicateColumnError:
                pass

        # =================================================================
        # Outreach Drafts table
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS outreach_drafts (
                id BIGSERIAL PRIMARY KEY,
                document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE UNIQUE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_outreach_drafts_doc
            ON outreach_drafts(document_id)
        """)

        # =================================================================
        # Automation Rules table
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_rules (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                trigger_event TEXT NOT NULL,
                conditions JSONB NOT NULL DEFAULT '{}',
                action TEXT NOT NULL,
                action_config JSONB NOT NULL DEFAULT '{}',
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_automation_rules_user
            ON automation_rules(user_id)
        """)

        # =================================================================
        # Automation Runs table (audit log)
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS automation_runs (
                id BIGSERIAL PRIMARY KEY,
                rule_id BIGINT NOT NULL REFERENCES automation_rules(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                list_id BIGINT,
                matched_accounts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'running',
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_automation_runs_rule
            ON automation_runs(rule_id, created_at DESC)
        """)

        # =================================================================
        # Materials tables (v2 - for uploaded sales materials)
        # Only create if materials feature is enabled (requires pgvector)
        # =================================================================
        if settings.materials_enabled:
            # Materials metadata table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS materials (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

                    -- File info
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER,
                    storage_key TEXT NOT NULL,

                    -- Classification
                    material_type TEXT DEFAULT 'other',

                    -- Processing status
                    status TEXT DEFAULT 'pending',
                    chunk_count INTEGER DEFAULT 0,
                    error_message TEXT,

                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_materials_user
                ON materials(user_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_materials_status
                ON materials(user_id, status)
            """)

            # Material chunks with vector embeddings
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS material_chunks (
                    id BIGSERIAL PRIMARY KEY,
                    material_id BIGINT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector(1536),

                    -- Metadata for context
                    section_title TEXT,
                    material_type TEXT,

                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_user
                ON material_chunks(user_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_material
                ON material_chunks(material_id)
            """)

            # Vector similarity search index (IVFFlat)
            # Note: This index requires data to exist first, so we create it separately
            # and handle the case where it might fail on empty table
            try:
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chunks_embedding
                    ON material_chunks USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
            except Exception:
                # IVFFlat index creation may fail on empty table, which is fine
                # It will be created when data is added, or use HNSW instead
                pass

        # =================================================================
        # Organizations & Team tables
        # =================================================================
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                stripe_customer_id TEXT UNIQUE,
                bonus_credits INTEGER DEFAULT 0,
                billing_period_start TIMESTAMPTZ DEFAULT NOW(),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS org_members (
                id BIGSERIAL PRIMARY KEY,
                org_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
                joined_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(org_id, user_id)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_org_members_user
            ON org_members(user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_org_members_org
            ON org_members(org_id)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS org_invites (
                id BIGSERIAL PRIMARY KEY,
                org_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                email TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'viewer')),
                token TEXT UNIQUE NOT NULL,
                invited_by BIGINT NOT NULL REFERENCES users(id),
                accepted_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(org_id, email)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_org_invites_token
            ON org_invites(token)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_org_invites_email
            ON org_invites(email)
        """)

        # Add org_id column to users
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN org_id BIGINT REFERENCES organizations(id)")
        except asyncpg.exceptions.DuplicateColumnError:
            pass

        # Add org_id to org-shared tables
        for table in ["materials", "material_chunks", "lists", "webhooks"]:
            try:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN org_id BIGINT REFERENCES organizations(id)")
            except asyncpg.exceptions.DuplicateColumnError:
                pass
            except Exception:
                pass  # Table may not exist (e.g. materials when not enabled)

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
