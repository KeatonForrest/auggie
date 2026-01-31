"""Document database operations."""

import asyncpg
from typing import Optional

from models import ResearchDocument
import db._pool as _db


async def save_document(doc: ResearchDocument, user_id: int) -> int:
    """Save a research document and return its ID."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO research_documents (
                user_id, company_url, company_name, created_at,
                company_overview, projects_initiatives, confirmed_tech_stack,
                hiring_signals, business_problems, existential_data_points, product_fit,
                talking_points, recent_news, key_contacts, information_gaps,
                opportunity_score, pain_score, fit_score, timing_score, score_summary,
                pain_evidence, fit_evidence, timing_evidence,
                thinking_content, model_used,
                full_markdown
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26)
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
            doc.thinking_content,
            doc.model_used,
            doc.full_markdown,
        )
        return row['id']


async def get_document(doc_id: int, user_id: int) -> Optional[ResearchDocument]:
    """Retrieve a research document by ID (scoped to user)."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM research_documents WHERE id = $1 AND user_id = $2",
            doc_id, user_id
        )
        return _row_to_document(row) if row else None


async def get_all_documents(user_id: int, limit: int = 50) -> list[ResearchDocument]:
    """Get all research documents for a user, most recent first (summary only)."""
    async with _db._pool.acquire() as conn:
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
    async with _db._pool.acquire() as conn:
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
    async with _db._pool.acquire() as conn:
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
        thinking_content=row.get("thinking_content"),
        model_used=row.get("model_used"),
        full_markdown="",
    )


async def get_recent_document_by_url(user_id: int, company_url: str, hours: int = 24) -> Optional[ResearchDocument]:
    """Find a recent research document for this URL within the time window."""
    async with _db._pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, company_name, created_at FROM research_documents
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
