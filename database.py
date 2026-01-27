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
        min_size=2,
        max_size=10,
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
            VALUES ($1, $2, $3, $4, 3)
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
            VALUES ($1, $2, $3, $4, 3)
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
    """Add credits to a user. Returns new total."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET bonus_credits = bonus_credits + $2
            WHERE id = $1
            RETURNING bonus_credits
            """,
            user_id, credits
        )
        return row['bonus_credits']


async def use_credit(user_id: int) -> bool:
    """Use one credit. Returns True if successful, False if no credits."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET bonus_credits = bonus_credits - 1
            WHERE id = $1 AND bonus_credits > 0
            RETURNING bonus_credits
            """,
            user_id
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
                talking_points, recent_news, key_contacts, information_gaps, full_markdown
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
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
    """Get all research documents for a user, most recent first."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM research_documents
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
        return [_row_to_document(row) for row in rows]


async def search_documents(user_id: int, query: str) -> list[ResearchDocument]:
    """Search documents by company name or URL (scoped to user)."""
    async with _pool.acquire() as conn:
        search_term = f"%{query}%"
        rows = await conn.fetch(
            """
            SELECT * FROM research_documents
            WHERE user_id = $1 AND (company_name ILIKE $2 OR company_url ILIKE $2)
            ORDER BY created_at DESC
            LIMIT 20
            """,
            user_id, search_term
        )
        return [_row_to_document(row) for row in rows]


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
        full_markdown=row["full_markdown"] or "",
    )


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


async def delete_chunks_for_material(material_id: int) -> None:
    """Delete all chunks for a material."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM material_chunks WHERE material_id = $1",
            material_id
        )
