"""database.py - PostgreSQL database operations for research documents."""

import asyncpg
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from models import ResearchDocument
from config import get_settings

# Connection pool (initialized on startup)
_pool: Optional[asyncpg.Pool] = None


async def init_database():
    """Initialize connection pool and create tables if they don't exist."""
    global _pool
    settings = get_settings()

    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=5,
        max_size=20,
        statement_cache_size=0,  # Disable cache to handle schema changes
    )

    async with _pool.acquire() as conn:
        # Enable pgvector extension for materials feature (only if enabled)
        if settings.materials_enabled:
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except asyncpg.exceptions.FeatureNotSupportedError:
                print("WARNING: pgvector extension not available. Materials feature will not work.")
                print("To enable materials, install pgvector on your PostgreSQL server.")
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

        # Fulfilled sessions table (idempotent Stripe fulfillment)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS fulfilled_sessions (
                session_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                credits INTEGER NOT NULL,
                fulfilled_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

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


# =============================================================================
# User Operations
# =============================================================================

async def get_user_by_google_id(google_id: str) -> Optional[dict]:
    """Get a user by their Google ID."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE google_id = $1",
            google_id
        )
        return dict(row) if row else None


async def get_user_by_microsoft_id(microsoft_id: str) -> Optional[dict]:
    """Get a user by their Microsoft ID."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE microsoft_id = $1",
            microsoft_id
        )
        return dict(row) if row else None


async def get_user_by_id(user_id: int) -> Optional[dict]:
    """Get a user by their ID."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE id = $1",
            user_id
        )
        return dict(row) if row else None


async def create_user(email: str, name: str, picture: str, google_id: str) -> dict:
    """Create a new user from Google OAuth data."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, name, picture, google_id, bonus_credits)
            VALUES ($1, $2, $3, $4, 100)
            RETURNING *
            """,
            email, name, picture, google_id
        )
        return dict(row)


async def create_user_microsoft(email: str, name: str, picture: str, microsoft_id: str) -> dict:
    """Create a new user from Microsoft OAuth data."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, name, picture, microsoft_id, bonus_credits)
            VALUES ($1, $2, $3, $4, 100)
            RETURNING *
            """,
            email, name, picture, microsoft_id
        )
        return dict(row)


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
    )

    async with _pool.acquire() as conn:
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
                competitors = $11
            WHERE id = $1
            RETURNING *
            """,
            user_id, company_name, product_context,
            product_name, product_description, problems_solved, differentiators,
            target_company_size, target_industries, target_personas, competitors
        )
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
    async with _pool.acquire() as conn:
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


async def increment_user_searches(user_id: int) -> int:
    """Increment search count and return new value."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET searches_used = searches_used + 1
            WHERE id = $1
            RETURNING searches_used
            """,
            user_id
        )
        return row['searches_used']


async def reset_user_searches(user_id: int) -> None:
    """Reset search count for new billing period."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET searches_used = 0, billing_period_start = NOW()
            WHERE id = $1
            """,
            user_id
        )


async def get_user_usage(user_id: int) -> dict:
    """Get user's current usage stats."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT searches_used, bonus_credits, billing_period_start, subscription_status, is_admin
            FROM users WHERE id = $1
            """,
            user_id
        )
        return dict(row) if row else None


async def add_credits(user_id: int, credits: int) -> int:
    """Add credits to a user. Credits are in whole units (1 credit = 100 cents internally).
    Returns new total in cents."""
    cents = credits * 100
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET bonus_credits = bonus_credits + $2
            WHERE id = $1
            RETURNING bonus_credits
            """,
            user_id, cents
        )
        return row['bonus_credits']


async def use_credit(user_id: int, cents: int = 100) -> bool:
    """Use credits. Default 100 cents (1 credit). Enrichment = 50 cents.
    Returns True if successful, False if insufficient credits."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET bonus_credits = bonus_credits - $2
            WHERE id = $1 AND bonus_credits >= $2
            RETURNING bonus_credits
            """,
            user_id, cents
        )
        return row is not None


async def refund_credit(user_id: int, cents: int = 100) -> None:
    """Refund credits (e.g. when a reserved job fails)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET bonus_credits = bonus_credits + $2 WHERE id = $1",
            user_id, cents
        )


async def fulfill_session(session_id: str, user_id: int, credits: int) -> bool:
    """Idempotently fulfill a Stripe checkout session.

    Inserts into fulfilled_sessions and adds credits in one transaction.
    Returns True if credits were added, False if already fulfilled.
    """
    cents = credits * 100
    async with _pool.acquire() as conn:
        async with conn.transaction():
            try:
                await conn.execute(
                    "INSERT INTO fulfilled_sessions (session_id, user_id, credits) VALUES ($1, $2, $3)",
                    session_id, user_id, credits,
                )
            except asyncpg.exceptions.UniqueViolationError:
                return False
            await conn.execute(
                "UPDATE users SET bonus_credits = bonus_credits + $2 WHERE id = $1",
                user_id, cents,
            )
            return True


async def try_start_list_analysis(list_id: int) -> bool:
    """Atomically transition a list to 'analyzing' status.

    Returns True if the transition succeeded, False if already analyzing.
    """
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE lists SET status = 'analyzing', updated_at = NOW() WHERE id = $1 AND status != 'analyzing' RETURNING id",
            list_id,
        )
        return row is not None


async def set_admin(email: str, is_admin: bool = True) -> bool:
    """Set admin status for a user by email. Returns True if updated."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE users
            SET is_admin = $2
            WHERE email = $1
            """,
            email, is_admin
        )
        return result == "UPDATE 1"


# =============================================================================
# Document Operations
# =============================================================================

async def save_document(doc: ResearchDocument, user_id: int) -> int:
    """Save a research document and return its ID."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO research_documents (
                user_id, company_url, company_name, created_at,
                company_overview, projects_initiatives, confirmed_tech_stack,
                hiring_signals, business_problems, existential_data_points, product_fit,
                talking_points, recent_news, key_contacts, information_gaps,
                opportunity_score, pain_score, fit_score, timing_score, score_summary,
                pain_evidence, fit_evidence, timing_evidence,
                full_markdown
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24)
            RETURNING id
            """,
            user_id,
            doc.company_url,
            doc.company_name,
            doc.created_at,
            doc.company_overview,
            doc.projects_initiatives,
            doc.confirmed_tech_stack,
            doc.hiring_signals,
            doc.business_problems,
            doc.existential_data_points,
            doc.product_fit,
            doc.talking_points,
            doc.recent_news,
            doc.key_contacts,
            doc.information_gaps,
            doc.opportunity_score,
            doc.pain_score,
            doc.fit_score,
            doc.timing_score,
            doc.score_summary,
            doc.pain_evidence,
            doc.fit_evidence,
            doc.timing_evidence,
            doc.full_markdown,
        )
        return row['id']


async def get_document(doc_id: int, user_id: int) -> Optional[ResearchDocument]:
    """Retrieve a research document by ID (scoped to user)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM research_documents WHERE id = $1 AND user_id = $2",
            doc_id, user_id
        )
        return _row_to_document(row) if row else None


async def get_all_documents(user_id: int, limit: int = 50) -> list[ResearchDocument]:
    """Get all research documents for a user, most recent first (summary only)."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, company_url, company_name, created_at,
                   company_overview, projects_initiatives, confirmed_tech_stack,
                   hiring_signals, business_problems, existential_data_points,
                   product_fit, talking_points, recent_news, key_contacts,
                   information_gaps,
                   opportunity_score, pain_score, fit_score, timing_score,
                   score_summary, pain_evidence, fit_evidence, timing_evidence
            FROM research_documents
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
        return [_row_to_document_summary(row) for row in rows]


async def search_documents(user_id: int, query: str) -> list[ResearchDocument]:
    """Search documents by company name or URL (scoped to user)."""
    async with _pool.acquire() as conn:
        search_term = f"%{query}%"
        rows = await conn.fetch(
            """
            SELECT id, user_id, company_url, company_name, created_at,
                   company_overview, projects_initiatives, confirmed_tech_stack,
                   hiring_signals, business_problems, existential_data_points,
                   product_fit, talking_points, recent_news, key_contacts,
                   information_gaps,
                   opportunity_score, pain_score, fit_score, timing_score,
                   score_summary, pain_evidence, fit_evidence, timing_evidence
            FROM research_documents
            WHERE user_id = $1 AND (company_name ILIKE $2 OR company_url ILIKE $2)
            ORDER BY created_at DESC
            LIMIT 20
            """,
            user_id, search_term
        )
        return [_row_to_document_summary(row) for row in rows]


async def delete_document(doc_id: int, user_id: int) -> bool:
    """Delete a document (scoped to user). Returns True if deleted."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM research_documents WHERE id = $1 AND user_id = $2",
            doc_id, user_id
        )
        return result == "DELETE 1"


def _row_to_document(row: asyncpg.Record) -> ResearchDocument:
    """Convert a database row to a ResearchDocument."""
    return ResearchDocument(
        id=row["id"],
        company_url=row["company_url"],
        company_name=row["company_name"],
        created_at=row["created_at"],
        company_overview=row["company_overview"] or "",
        projects_initiatives=row["projects_initiatives"] or "",
        confirmed_tech_stack=row["confirmed_tech_stack"] or "",
        hiring_signals=row["hiring_signals"] or "",
        business_problems=row["business_problems"] or "",
        existential_data_points=row.get("existential_data_points") or "",
        product_fit=row["product_fit"] or "",
        talking_points=row["talking_points"] or "",
        recent_news=row["recent_news"] or "",
        key_contacts=row.get("key_contacts") or "",
        information_gaps=row["information_gaps"] or "",
        opportunity_score=row.get("opportunity_score"),
        pain_score=row.get("pain_score"),
        fit_score=row.get("fit_score"),
        timing_score=row.get("timing_score"),
        score_summary=row.get("score_summary"),
        pain_evidence=row.get("pain_evidence"),
        fit_evidence=row.get("fit_evidence"),
        timing_evidence=row.get("timing_evidence"),
        full_markdown=row["full_markdown"] or "",
    )


def _row_to_document_summary(row: asyncpg.Record) -> ResearchDocument:
    """Convert a database row (without full_markdown) to a ResearchDocument."""
    return ResearchDocument(
        id=row["id"],
        company_url=row["company_url"],
        company_name=row["company_name"],
        created_at=row["created_at"],
        company_overview=row["company_overview"] or "",
        projects_initiatives=row["projects_initiatives"] or "",
        confirmed_tech_stack=row["confirmed_tech_stack"] or "",
        hiring_signals=row["hiring_signals"] or "",
        business_problems=row["business_problems"] or "",
        existential_data_points=row.get("existential_data_points") or "",
        product_fit=row["product_fit"] or "",
        talking_points=row["talking_points"] or "",
        recent_news=row["recent_news"] or "",
        key_contacts=row.get("key_contacts") or "",
        information_gaps=row["information_gaps"] or "",
        opportunity_score=row.get("opportunity_score"),
        pain_score=row.get("pain_score"),
        fit_score=row.get("fit_score"),
        timing_score=row.get("timing_score"),
        score_summary=row.get("score_summary"),
        pain_evidence=row.get("pain_evidence"),
        fit_evidence=row.get("fit_evidence"),
        timing_evidence=row.get("timing_evidence"),
        full_markdown="",
    )


# =============================================================================
# API Key Operations
# =============================================================================

async def create_api_key_record(user_id: int, key_hash: str, prefix: str, name: str = "Default") -> int:
    """Store a new API key hash. Returns the key ID."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_keys (user_id, key_hash, prefix, name)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            user_id, key_hash, prefix, name
        )
        return row["id"]


async def validate_api_key(raw_key: str) -> dict | None:
    """Validate a raw API key against stored hashes.

    Returns {"user_id": ..., "api_key_id": ...} on success, None on failure.
    """
    from api.keys import verify_api_key

    prefix = raw_key[:16]
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, key_hash FROM api_keys WHERE prefix = $1 AND NOT revoked",
            prefix
        )
        for row in rows:
            if verify_api_key(raw_key, row["key_hash"]):
                # Update last_used_at
                await conn.execute(
                    "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1",
                    row["id"]
                )
                return {"user_id": row["user_id"], "api_key_id": row["id"]}
    return None


async def list_api_keys(user_id: int) -> list[dict]:
    """List all active API keys for a user (no hashes returned)."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, prefix, name, created_at, last_used_at
            FROM api_keys
            WHERE user_id = $1 AND NOT revoked
            ORDER BY created_at DESC
            """,
            user_id
        )
        return [dict(row) for row in rows]


async def revoke_api_key(key_id: int, user_id: int) -> bool:
    """Revoke an API key (scoped to user). Returns True if revoked."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE api_keys SET revoked = TRUE WHERE id = $1 AND user_id = $2 AND NOT revoked",
            key_id, user_id
        )
        return result == "UPDATE 1"


async def record_api_usage(api_key_id: int, endpoint: str, credits_used: int = 1):
    """Log an API call for usage tracking."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO api_usage (api_key_id, endpoint, credits_used) VALUES ($1, $2, $3)",
            api_key_id, endpoint, credits_used
        )


async def get_api_key_usage_stats(user_id: int) -> dict[int, dict]:
    """Get per-key usage stats (request count, credits used) for a user's active keys."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ak.id AS key_id,
                   COALESCE(COUNT(au.id), 0) AS request_count,
                   COALESCE(SUM(au.credits_used), 0) AS credits_used
            FROM api_keys ak
            LEFT JOIN api_usage au ON au.api_key_id = ak.id
            WHERE ak.user_id = $1 AND NOT ak.revoked
            GROUP BY ak.id
            """,
            user_id
        )
        return {row["key_id"]: {"requests": row["request_count"], "credits": row["credits_used"]} for row in rows}


# =============================================================================
# Enriched Contacts Operations
# =============================================================================

async def save_enriched_contacts(document_id: int, user_id: int, contacts: list[dict]):
    """Save enriched contacts for a research document."""
    async with _pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO enriched_contacts
                (document_id, user_id, name, first_name, last_name, title, email, email_status, profile_url, company_name)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            [
                (
                    document_id, user_id,
                    c.get("name"), c.get("first_name"), c.get("last_name"),
                    c.get("title"), c.get("email"), c.get("email_status"),
                    c.get("profile_url"), c.get("company_name"),
                )
                for c in contacts
            ],
        )


async def get_enriched_contacts(document_id: int, user_id: int) -> list[dict]:
    """Get enriched contacts for a document (scoped to user)."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM enriched_contacts WHERE document_id = $1 AND user_id = $2 ORDER BY id",
            document_id, user_id
        )
        return [dict(row) for row in rows]


# =============================================================================
# Materials Operations (v2)
# =============================================================================

async def create_material(
    user_id: int,
    filename: str,
    file_type: str,
    file_size: int,
    storage_key: str,
    material_type: str = "other"
) -> dict:
    """Create a new material record."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO materials (user_id, filename, file_type, file_size, storage_key, material_type)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            user_id, filename, file_type, file_size, storage_key, material_type
        )
        return dict(row)


async def update_material_status(
    material_id: int,
    status: str,
    chunk_count: int = 0,
    error_message: str = None
) -> None:
    """Update material processing status."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE materials
            SET status = $2, chunk_count = $3, error_message = $4, updated_at = NOW()
            WHERE id = $1
            """,
            material_id, status, chunk_count, error_message
        )


async def get_user_materials(user_id: int) -> list[dict]:
    """Get all materials for a user."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, filename, file_type, file_size, material_type, status, chunk_count, error_message, created_at
            FROM materials
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id
        )
        return [dict(row) for row in rows]


async def get_material(material_id: int, user_id: int) -> Optional[dict]:
    """Get a material by ID (scoped to user)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM materials WHERE id = $1 AND user_id = $2",
            material_id, user_id
        )
        return dict(row) if row else None


async def delete_material(material_id: int, user_id: int) -> Optional[str]:
    """Delete a material and return its storage key for R2 cleanup."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM materials WHERE id = $1 AND user_id = $2 RETURNING storage_key",
            material_id, user_id
        )
        return row['storage_key'] if row else None


# =============================================================================
# Chunk Operations (v2)
# =============================================================================

async def save_chunks(
    material_id: int,
    user_id: int,
    chunks: list[dict],
) -> int:
    """Save chunks with embeddings. Returns count saved."""
    async with _pool.acquire() as conn:
        for i, chunk in enumerate(chunks):
            # Convert embedding list to pgvector format
            embedding = chunk['embedding']
            embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'

            await conn.execute(
                """
                INSERT INTO material_chunks (material_id, user_id, chunk_index, content, embedding, section_title, material_type)
                VALUES ($1, $2, $3, $4, $5::vector, $6, $7)
                """,
                material_id, user_id, i, chunk['content'], embedding_str,
                chunk.get('section_title'), chunk.get('material_type')
            )

        return len(chunks)


async def vector_search(
    user_id: int,
    query_embedding: list[float],
    limit: int = 5
) -> list[dict]:
    """Search for similar chunks using vector similarity."""
    async with _pool.acquire() as conn:
        # Convert Python list to pgvector format
        embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

        rows = await conn.fetch(
            """
            SELECT
                content,
                section_title,
                material_type,
                1 - (embedding <=> $2::vector) as similarity
            FROM material_chunks
            WHERE user_id = $1
            ORDER BY embedding <=> $2::vector
            LIMIT $3
            """,
            user_id, embedding_str, limit
        )

        return [dict(row) for row in rows]


async def get_material_preview(material_id: int, user_id: int, limit: int = 5) -> str:
    """Fetch first N chunks by chunk_index and return concatenated content."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT content FROM material_chunks
            WHERE material_id = $1 AND user_id = $2
            ORDER BY chunk_index
            LIMIT $3
            """,
            material_id, user_id, limit
        )
        return "\n\n".join(row["content"] for row in rows)


async def delete_chunks_for_material(material_id: int) -> None:
    """Delete all chunks for a material."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM material_chunks WHERE material_id = $1",
            material_id
        )


# =============================================================================
# Research Jobs Operations
# =============================================================================

async def create_research_job(user_id: int, api_key_id: int | None, company_url: str) -> dict:
    """Create a new research job. Returns the job record."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO research_jobs (user_id, api_key_id, company_url)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            user_id, api_key_id, company_url
        )
        return dict(row)


async def get_research_job(job_id: int, user_id: int) -> Optional[dict]:
    """Get a research job by ID (scoped to user)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM research_jobs WHERE id = $1 AND user_id = $2",
            job_id, user_id
        )
        return dict(row) if row else None


async def update_job_status(
    job_id: int,
    status: str,
    document_id: int = None,
    error_message: str = None,
) -> None:
    """Update a job's status and optional result fields."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE research_jobs
            SET status = $2, document_id = $3, error_message = $4,
                completed_at = CASE WHEN $2 IN ('completed', 'failed') THEN NOW() ELSE completed_at END
            WHERE id = $1
            """,
            job_id, status, document_id, error_message
        )


async def list_user_jobs(user_id: int, limit: int = 20) -> list[dict]:
    """List recent research jobs for a user."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, company_url, status, document_id, error_message, created_at, completed_at
            FROM research_jobs
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
        return [dict(row) for row in rows]


# =============================================================================
# Webhook Operations
# =============================================================================

async def upsert_webhook(user_id: int, url: str, secret: str) -> dict:
    """Create or update user's webhook. Returns the webhook record."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO webhooks (user_id, url, secret)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
            SET url = EXCLUDED.url, secret = EXCLUDED.secret, active = TRUE
            RETURNING *
            """,
            user_id, url, secret
        )
        return dict(row)


async def get_user_webhook(user_id: int) -> Optional[dict]:
    """Get a user's active webhook config."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM webhooks WHERE user_id = $1 AND active = TRUE",
            user_id
        )
        return dict(row) if row else None


async def delete_user_webhook(user_id: int) -> bool:
    """Deactivate user's webhook. Returns True if found."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE webhooks SET active = FALSE WHERE user_id = $1 AND active = TRUE",
            user_id
        )
        return result == "UPDATE 1"


# =============================================================================
# Webhook Delivery Operations
# =============================================================================

async def create_webhook_delivery(webhook_id: int, job_id: int) -> dict:
    """Create a delivery record. Returns the record."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO webhook_deliveries (webhook_id, job_id)
            VALUES ($1, $2)
            RETURNING *
            """,
            webhook_id, job_id
        )
        return dict(row)


async def update_delivery_status(
    delivery_id: int,
    status: str,
    http_status: int = None,
    error_message: str = None,
) -> None:
    """Update a webhook delivery result."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE webhook_deliveries
            SET status = $2, http_status = $3, error_message = $4, attempts = attempts + 1
            WHERE id = $1
            """,
            delivery_id, status, http_status, error_message
        )


# =============================================================================
# Bulk Job Operations
# =============================================================================

async def create_bulk_job(user_id: int, api_key_id: int, name: str | None, total_items: int, credits_reserved: int) -> dict:
    """Create a new bulk job. Returns the job record."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO bulk_jobs (user_id, api_key_id, name, total_items, credits_reserved)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            user_id, api_key_id, name, total_items, credits_reserved
        )
        return dict(row)


async def get_bulk_job(bulk_job_id: int, user_id: int) -> dict | None:
    """Get a bulk job by ID (scoped to user)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bulk_jobs WHERE id = $1 AND user_id = $2",
            bulk_job_id, user_id
        )
        return dict(row) if row else None


async def list_bulk_jobs(user_id: int, limit: int = 20) -> list[dict]:
    """List recent bulk jobs for a user."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, status, total_items, completed_items, failed_items,
                   credits_reserved, created_at, completed_at
            FROM bulk_jobs
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
        return [dict(row) for row in rows]


async def create_bulk_job_items(bulk_job_id: int, urls: list[str]) -> list[dict]:
    """Batch-insert items for a bulk job. Returns list of item records."""
    async with _pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO bulk_job_items (bulk_job_id, company_url) VALUES ($1, $2)",
            [(bulk_job_id, url) for url in urls],
        )
        rows = await conn.fetch(
            "SELECT * FROM bulk_job_items WHERE bulk_job_id = $1 ORDER BY id",
            bulk_job_id,
        )
        return [dict(row) for row in rows]


async def get_bulk_job_items(bulk_job_id: int) -> list[dict]:
    """Get all items for a bulk job."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, bulk_job_id, research_job_id, company_url, status,
                   document_id, error_message, created_at, completed_at
            FROM bulk_job_items
            WHERE bulk_job_id = $1
            ORDER BY id
            """,
            bulk_job_id
        )
        return [dict(row) for row in rows]


async def update_bulk_job_item(
    item_id: int,
    status: str,
    research_job_id: int | None = None,
    document_id: int | None = None,
    error_message: str | None = None,
) -> None:
    """Update a bulk job item and atomically increment parent counters."""
    async with _pool.acquire() as conn:
        async with conn.transaction():
            # Update the item
            await conn.execute(
                """
                UPDATE bulk_job_items
                SET status = $2, research_job_id = $3, document_id = $4,
                    error_message = $5,
                    completed_at = CASE WHEN $2 IN ('completed', 'failed') THEN NOW() ELSE completed_at END
                WHERE id = $1
                """,
                item_id, status, research_job_id, document_id, error_message
            )
            # Increment parent counters
            if status == 'completed':
                await conn.execute(
                    """
                    UPDATE bulk_jobs SET completed_items = completed_items + 1
                    WHERE id = (SELECT bulk_job_id FROM bulk_job_items WHERE id = $1)
                    """,
                    item_id
                )
            elif status == 'failed':
                await conn.execute(
                    """
                    UPDATE bulk_jobs SET failed_items = failed_items + 1
                    WHERE id = (SELECT bulk_job_id FROM bulk_job_items WHERE id = $1)
                    """,
                    item_id
                )


async def finalize_bulk_job(bulk_job_id: int) -> dict:
    """Set final status and completed_at on a bulk job. Returns updated record."""
    async with _pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT total_items, completed_items, failed_items FROM bulk_jobs WHERE id = $1 FOR UPDATE",
                bulk_job_id
            )
            if row["failed_items"] == row["total_items"]:
                final_status = "failed"
            elif row["failed_items"] > 0:
                final_status = "partial_failure"
            else:
                final_status = "completed"

            updated = await conn.fetchrow(
                """
                UPDATE bulk_jobs SET status = $2, completed_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                bulk_job_id, final_status
            )
            return dict(updated)


# =============================================================================
# List Operations
# =============================================================================

async def create_list(user_id: int, api_key_id: int | None, name: str) -> dict:
    """Create a new list. Returns the list record."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO lists (user_id, api_key_id, name)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            user_id, api_key_id, name
        )
        return dict(row)


async def get_list(list_id: int, user_id: int) -> dict | None:
    """Get a list by ID (scoped to user)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM lists WHERE id = $1 AND user_id = $2",
            list_id, user_id
        )
        return dict(row) if row else None


async def list_lists(user_id: int, limit: int = 20) -> list[dict]:
    """List recent lists for a user (summaries)."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, status, total_accounts, analyzed_accounts,
                   failed_accounts, credits_reserved, created_at, updated_at
            FROM lists
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
        return [dict(row) for row in rows]


async def delete_list(list_id: int, user_id: int) -> bool:
    """Delete a list and all its accounts (scoped to user). Returns True if deleted."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM lists WHERE id = $1 AND user_id = $2",
            list_id, user_id
        )
        return result == "DELETE 1"


async def add_list_accounts(list_id: int, company_urls: list[str]) -> list[dict]:
    """Batch-insert accounts for a list. Updates total_accounts on parent. Returns account records."""
    async with _pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO list_accounts (list_id, company_url) VALUES ($1, $2)",
            [(list_id, url) for url in company_urls],
        )
        await conn.execute(
            "UPDATE lists SET total_accounts = $2, updated_at = NOW() WHERE id = $1",
            list_id, len(company_urls)
        )
        rows = await conn.fetch(
            "SELECT * FROM list_accounts WHERE list_id = $1 ORDER BY id",
            list_id,
        )
        return [dict(row) for row in rows]


async def get_list_accounts(
    list_id: int,
    min_pain: int | None = None,
    min_composite: int | None = None,
    sort_by: str = "composite_score",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Get accounts for a list with optional filtering and sorting."""
    allowed_sorts = {"pain_score", "composite_score", "fit_score", "timing_score", "company_name"}
    if sort_by not in allowed_sorts:
        sort_by = "composite_score"
    if order not in ("asc", "desc"):
        order = "desc"

    conditions = ["list_id = $1"]
    params: list = [list_id]
    idx = 2

    if min_pain is not None:
        conditions.append(f"pain_score >= ${idx}")
        params.append(min_pain)
        idx += 1
    if min_composite is not None:
        conditions.append(f"composite_score >= ${idx}")
        params.append(min_composite)
        idx += 1

    where = " AND ".join(conditions)
    # Use NULLS LAST so un-analyzed accounts sort to the end
    query = f"""
        SELECT id, list_id, company_url, status, document_id, research_job_id,
               pain_score, fit_score, timing_score, composite_score,
               company_name, error_message, created_at, analyzed_at
        FROM list_accounts
        WHERE {where}
        ORDER BY {sort_by} {order} NULLS LAST
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    params.extend([limit, offset])

    async with _pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]


async def update_list_account(
    account_id: int,
    status: str,
    document_id: int | None = None,
    research_job_id: int | None = None,
    pain_score: int | None = None,
    fit_score: int | None = None,
    timing_score: int | None = None,
    composite_score: int | None = None,
    company_name: str | None = None,
    error_message: str | None = None,
) -> None:
    """Update a list account and atomically increment parent counters."""
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE list_accounts
                SET status = $2, document_id = $3, research_job_id = $4,
                    pain_score = $5, fit_score = $6, timing_score = $7, composite_score = $8,
                    company_name = $9, error_message = $10,
                    analyzed_at = CASE WHEN $2 IN ('completed', 'failed') THEN NOW() ELSE analyzed_at END
                WHERE id = $1
                """,
                account_id, status, document_id, research_job_id,
                pain_score, fit_score, timing_score, composite_score,
                company_name, error_message
            )
            if status == 'completed':
                await conn.execute(
                    """
                    UPDATE lists SET analyzed_accounts = analyzed_accounts + 1, updated_at = NOW()
                    WHERE id = (SELECT list_id FROM list_accounts WHERE id = $1)
                    """,
                    account_id
                )
            elif status == 'failed':
                await conn.execute(
                    """
                    UPDATE lists SET failed_accounts = failed_accounts + 1, updated_at = NOW()
                    WHERE id = (SELECT list_id FROM list_accounts WHERE id = $1)
                    """,
                    account_id
                )


async def finalize_list(list_id: int) -> dict:
    """Set final status on a list. Returns updated record."""
    async with _pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT total_accounts, analyzed_accounts, failed_accounts FROM lists WHERE id = $1 FOR UPDATE",
                list_id
            )
            if row["failed_accounts"] == row["total_accounts"]:
                final_status = "failed"
            elif row["failed_accounts"] > 0:
                final_status = "partial_failure"
            else:
                final_status = "completed"

            updated = await conn.fetchrow(
                """
                UPDATE lists SET status = $2, updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                list_id, final_status
            )
            return dict(updated)


async def update_list_status(list_id: int, status: str) -> None:
    """Update the status of a list."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE lists SET status = $2, updated_at = NOW() WHERE id = $1",
            list_id, status
        )


async def update_list_credits(list_id: int, credits_reserved: int) -> None:
    """Update credits reserved on a list."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE lists SET credits_reserved = $2, updated_at = NOW() WHERE id = $1",
            list_id, credits_reserved
        )


async def get_recent_document_by_url(user_id: int, company_url: str, hours: int = 24) -> Optional[ResearchDocument]:
    """Find a recent research document for this URL within the time window."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM research_documents
            WHERE user_id = $1 AND company_url = $2
              AND created_at > NOW() - make_interval(hours => $3)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id, company_url, hours
        )
        return _row_to_document(row) if row else None


async def check_duplicate_research(user_id: int, company_url: str, days: int = 7) -> dict | None:
    """Check if a research document exists for this URL within the last N days."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, company_name, created_at
            FROM research_documents
            WHERE user_id = $1 AND company_url = $2
              AND created_at > NOW() - make_interval(days => $3)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id, company_url, days
        )
        return dict(row) if row else None


async def get_list_account(account_id: int, list_id: int) -> dict | None:
    """Get a single list account by ID scoped to a list."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM list_accounts WHERE id = $1 AND list_id = $2",
            account_id, list_id
        )
        return dict(row) if row else None


async def reset_list_account(account_id: int) -> None:
    """Reset a failed list account to pending for retry."""
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE list_accounts
                SET status = 'pending', error_message = NULL, research_job_id = NULL
                WHERE id = $1
                """,
                account_id
            )
            # Decrement failed counter on parent list
            await conn.execute(
                """
                UPDATE lists SET failed_accounts = GREATEST(failed_accounts - 1, 0), updated_at = NOW()
                WHERE id = (SELECT list_id FROM list_accounts WHERE id = $1)
                """,
                account_id
            )


async def get_pending_list_accounts(list_id: int) -> list[dict]:
    """Get all pending accounts for a list."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM list_accounts WHERE list_id = $1 AND status = 'pending' ORDER BY id",
            list_id
        )
        return [dict(row) for row in rows]


# =============================================================================
# Integration Operations
# =============================================================================

async def upsert_integration(
    user_id: int,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    token_expires_at: datetime | None = None,
    metadata: dict | None = None,
) -> dict:
    """Create or update an integration for a user."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO integrations (user_id, provider, access_token, refresh_token, token_expires_at, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (user_id, provider) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = COALESCE(EXCLUDED.refresh_token, integrations.refresh_token),
                token_expires_at = EXCLUDED.token_expires_at,
                metadata = COALESCE(EXCLUDED.metadata, integrations.metadata),
                updated_at = NOW()
            RETURNING *
            """,
            user_id, provider, access_token, refresh_token, token_expires_at,
            __import__('json').dumps(metadata or {}),
        )
        return dict(row)


async def get_integration(user_id: int, provider: str) -> dict | None:
    """Get a user's integration for a provider."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM integrations WHERE user_id = $1 AND provider = $2",
            user_id, provider,
        )
        return dict(row) if row else None


async def get_user_integrations(user_id: int) -> list[dict]:
    """Get all integrations for a user."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM integrations WHERE user_id = $1 ORDER BY provider",
            user_id,
        )
        return [dict(row) for row in rows]


async def delete_integration(user_id: int, provider: str) -> bool:
    """Delete a user's integration. Returns True if deleted."""
    async with _pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM integrations WHERE user_id = $1 AND provider = $2",
            user_id, provider,
        )
        return result == "DELETE 1"


async def update_integration_tokens(
    user_id: int,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    token_expires_at: datetime | None = None,
) -> None:
    """Update tokens for an integration (used by refresh flow)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE integrations SET
                access_token = $3,
                refresh_token = COALESCE($4, refresh_token),
                token_expires_at = $5,
                updated_at = NOW()
            WHERE user_id = $1 AND provider = $2
            """,
            user_id, provider, access_token, refresh_token, token_expires_at,
        )


async def get_list_source(list_id: int) -> dict | None:
    """Get the source metadata for a list."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT source FROM lists WHERE id = $1",
            list_id,
        )
        if row and row["source"]:
            import json
            return json.loads(row["source"]) if isinstance(row["source"], str) else row["source"]
        return None


async def set_list_source(list_id: int, source: dict) -> None:
    """Set the source metadata for a list."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE lists SET source = $2::jsonb, updated_at = NOW() WHERE id = $1",
            list_id, __import__('json').dumps(source),
        )


async def update_list_account_pushed(account_id: int, provider: str, push_data: dict) -> None:
    """Mark a list account as pushed to a provider."""
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE list_accounts SET pushed_to = pushed_to || $2::jsonb
            WHERE id = $1
            """,
            account_id,
            __import__('json').dumps({provider: push_data}),
        )
