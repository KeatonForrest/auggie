"""Document database operations."""

import asyncpg
from typing import Optional

from models import ResearchDocument
from utils.slugs import slugify
import db._pool as _db


async def save_document(doc: ResearchDocument, user_id: int) -> int:
    """Save a research document and return its ID.

    Generates a slug from company_name, retrying with -2, -3 suffixes
    on unique constraint violation.
    """
    base_slug = slugify(doc.company_name)

    for attempt in range(1, 20):
        slug = base_slug if attempt == 1 else f"{base_slug}-{attempt}"
        try:
            async with _db._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO research_documents (
                        user_id, company_url, company_name, slug, created_at,
                        company_overview, projects_initiatives, confirmed_tech_stack,
                        hiring_signals, business_problems, existential_data_points, product_fit,
                        talking_points, recent_news, key_contacts, information_gaps,
                        opportunity_score, pain_score, fit_score, timing_score, score_summary,
                        pain_evidence, fit_evidence, timing_evidence,
                        thinking_content, model_used,
                        full_markdown,
                        before_scenario, pvp_seed, recommended_contacts, required_capabilities
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30, $31)
                    RETURNING id
                    """,
                    user_id,
                    doc.company_url,
                    doc.company_name,
                    slug,
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
                    doc.thinking_content,
                    doc.model_used,
                    doc.full_markdown,
                    doc.before_scenario,
                    doc.pvp_seed,
                    doc.recommended_contacts,
                    doc.required_capabilities,
                )
                return row['id']
        except asyncpg.UniqueViolationError as e:
            if "idx_documents_user_slug" in str(e):
                continue  # Try next suffix
            raise
    # Should never reach here, but just in case
    raise RuntimeError(f"Could not generate unique slug for '{doc.company_name}' after 19 attempts")


async def get_document(doc_id: int, user_id: int) -> Optional[ResearchDocument]:
    """Retrieve a research document by ID (scoped to user)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM research_documents WHERE id = $1 AND user_id = $2",
            doc_id, user_id
        )
        return _row_to_document(row) if row else None


async def get_document_by_share_token(doc_id: int, share_token: str) -> Optional[ResearchDocument]:
    """Retrieve a research document by ID + share token (for shared links)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM research_documents WHERE id = $1 AND share_token = $2",
            doc_id, share_token,
        )
        return _row_to_document(row) if row else None


async def get_document_og_meta(doc_id: int, share_token: Optional[str] = None) -> Optional[dict]:
    """Fetch minimal metadata for OG tags (requires share token)."""
    if not share_token:
        return None
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, company_name, company_url, share_token, opportunity_score,
                   pain_score, fit_score, timing_score, score_summary
            FROM research_documents WHERE id = $1 AND share_token = $2
            """,
            doc_id, share_token,
        )
        return dict(row) if row else None


async def get_share_token(doc_id: int, user_id: int) -> Optional[str]:
    """Get the share token for a document owned by the user."""
    async with _db._pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT share_token FROM research_documents WHERE id = $1 AND user_id = $2",
            doc_id, user_id,
        )


async def get_all_documents(user_id: int, limit: int = 50) -> list[ResearchDocument]:
    """Get all research documents for a user, most recent first (summary only)."""
    async with _db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, company_url, company_name, slug, created_at,
                   company_overview, projects_initiatives, confirmed_tech_stack,
                   hiring_signals, business_problems, existential_data_points,
                   product_fit, talking_points, recent_news, key_contacts,
                   information_gaps,
                   opportunity_score, pain_score, fit_score, timing_score,
                   score_summary, pain_evidence, fit_evidence, timing_evidence,
                   before_scenario, pvp_seed, recommended_contacts,
                   required_capabilities
            FROM research_documents
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
        return [_row_to_document_summary(row) for row in rows]


def _row_to_document(row: asyncpg.Record) -> ResearchDocument:
    """Convert a database row to a ResearchDocument."""
    return ResearchDocument(
        id=row["id"],
        company_url=row["company_url"],
        company_name=row["company_name"],
        slug=row.get("slug"),
        created_at=row["created_at"],
        company_overview=row["company_overview"] or "",
        projects_initiatives=row["projects_initiatives"] or "",
        confirmed_tech_stack=row["confirmed_tech_stack"] or "",
        hiring_signals=row["hiring_signals"] or "",
        business_problems=row["business_problems"] or "",
        existential_data_points=row.get("existential_data_points") or "",
        before_scenario=row.get("before_scenario") or "",
        pvp_seed=row.get("pvp_seed") or "",
        required_capabilities=row.get("required_capabilities") or "",
        product_fit=row["product_fit"] or "",
        talking_points=row["talking_points"] or "",
        recent_news=row["recent_news"] or "",
        key_contacts=row.get("key_contacts") or "",
        recommended_contacts=row.get("recommended_contacts") or "",
        information_gaps=row["information_gaps"] or "",
        opportunity_score=row.get("opportunity_score"),
        pain_score=row.get("pain_score"),
        fit_score=row.get("fit_score"),
        timing_score=row.get("timing_score"),
        score_summary=row.get("score_summary"),
        pain_evidence=row.get("pain_evidence"),
        fit_evidence=row.get("fit_evidence"),
        timing_evidence=row.get("timing_evidence"),
        thinking_content=row.get("thinking_content"),
        model_used=row.get("model_used"),
        full_markdown=row["full_markdown"] or "",
    )


def _row_to_document_summary(row: asyncpg.Record) -> ResearchDocument:
    """Convert a database row (without full_markdown) to a ResearchDocument."""
    return ResearchDocument(
        id=row["id"],
        company_url=row["company_url"],
        company_name=row["company_name"],
        slug=row.get("slug"),
        created_at=row["created_at"],
        company_overview=row["company_overview"] or "",
        projects_initiatives=row["projects_initiatives"] or "",
        confirmed_tech_stack=row["confirmed_tech_stack"] or "",
        hiring_signals=row["hiring_signals"] or "",
        business_problems=row["business_problems"] or "",
        existential_data_points=row.get("existential_data_points") or "",
        before_scenario=row.get("before_scenario") or "",
        pvp_seed=row.get("pvp_seed") or "",
        required_capabilities=row.get("required_capabilities") or "",
        product_fit=row["product_fit"] or "",
        talking_points=row["talking_points"] or "",
        recent_news=row["recent_news"] or "",
        key_contacts=row.get("key_contacts") or "",
        recommended_contacts=row.get("recommended_contacts") or "",
        information_gaps=row["information_gaps"] or "",
        opportunity_score=row.get("opportunity_score"),
        pain_score=row.get("pain_score"),
        fit_score=row.get("fit_score"),
        timing_score=row.get("timing_score"),
        score_summary=row.get("score_summary"),
        pain_evidence=row.get("pain_evidence"),
        fit_evidence=row.get("fit_evidence"),
        timing_evidence=row.get("timing_evidence"),
        thinking_content=row.get("thinking_content"),
        model_used=row.get("model_used"),
        full_markdown="",
    )


async def get_document_by_slug(org_slug: str, doc_slug: str) -> Optional[ResearchDocument]:
    """Retrieve a research document by org slug + document slug."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT rd.*
            FROM research_documents rd
            JOIN users u ON u.id = rd.user_id
            JOIN org_members om ON om.user_id = u.id
            JOIN organizations o ON o.id = om.org_id
            WHERE o.slug = $1 AND rd.slug = $2
            LIMIT 1
            """,
            org_slug, doc_slug,
        )
        return _row_to_document(row) if row else None


async def get_document_meta_by_slug(org_slug: str, doc_slug: str) -> Optional[dict]:
    """Fetch minimal metadata for a document by slug (for OG tags / previews)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT rd.id, rd.user_id, rd.company_name, rd.company_url,
                   rd.share_token, rd.slug,
                   rd.opportunity_score, rd.pain_score, rd.fit_score,
                   rd.timing_score, rd.score_summary,
                   o.slug AS org_slug
            FROM research_documents rd
            JOIN users u ON u.id = rd.user_id
            JOIN org_members om ON om.user_id = u.id
            JOIN organizations o ON o.id = om.org_id
            WHERE o.slug = $1 AND rd.slug = $2
            LIMIT 1
            """,
            org_slug, doc_slug,
        )
        return dict(row) if row else None


async def get_document_slug_path(doc_id: int, user_id: int) -> Optional[str]:
    """Return the vanity URL path (/@org_slug/doc_slug) for a document, or None."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT o.slug AS org_slug, rd.slug AS doc_slug
            FROM research_documents rd
            JOIN org_members om ON om.user_id = rd.user_id
            JOIN organizations o ON o.id = om.org_id
            WHERE rd.id = $1 AND rd.user_id = $2
            LIMIT 1
            """,
            doc_id, user_id,
        )
        if row:
            return f"/@{row['org_slug']}/{row['doc_slug']}"
        return None


async def get_recent_document_by_url(user_id: int, company_url: str, hours: int = 24) -> Optional[int]:
    """Find a recent research document for this URL within the time window. Returns document id or None."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id FROM research_documents
            WHERE user_id = $1 AND company_url = $2
              AND created_at > NOW() - make_interval(hours => $3)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id, company_url, hours
        )
        return row["id"] if row else None


async def check_duplicate_research(user_id: int, company_url: str, days: int = 7) -> dict | None:
    """Check if a research document exists for this URL within the last N days."""
    async with _db._pool.acquire() as conn:
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
