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
    )

    async with _pool.acquire() as conn:
        # Create users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,

                -- Auth
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                picture TEXT,
                google_id TEXT UNIQUE NOT NULL,

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
            INSERT INTO users (email, name, picture, google_id)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            email, name, picture, google_id
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
    """Build a rich product context string for Claude from onboarding data."""
    parts = [f"**Product:** {product_name}"]

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
            SELECT searches_used, billing_period_start, subscription_status
            FROM users WHERE id = $1
            """,
            user_id
        )
        return dict(row) if row else None


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
                hiring_signals, business_problems, product_fit,
                talking_points, recent_news, information_gaps, full_markdown
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
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
            doc.product_fit,
            doc.talking_points,
            doc.recent_news,
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
        product_fit=row["product_fit"] or "",
        talking_points=row["talking_points"] or "",
        recent_news=row["recent_news"] or "",
        information_gaps=row["information_gaps"] or "",
        full_markdown=row["full_markdown"] or "",
    )
