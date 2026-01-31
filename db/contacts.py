"""Enriched contacts database operations."""

from db._pool import _pool


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
