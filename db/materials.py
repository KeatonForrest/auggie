"""Materials and chunks database operations."""

from typing import Optional

from db._pool import _pool


async def create_material(
    user_id: int,
    filename: str,
    file_type: str,
    file_size: int,
    storage_key: str,
    material_type: str = "other"
) -> dict:
    """Create a new material record (org-scoped)."""
    async with _pool.acquire() as conn:
        org_id = await conn.fetchval("SELECT org_id FROM users WHERE id = $1", user_id)
        row = await conn.fetchrow(
            """
            INSERT INTO materials (user_id, org_id, filename, file_type, file_size, storage_key, material_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            user_id, org_id, filename, file_type, file_size, storage_key, material_type
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
    """Get all materials for a user's org (shared)."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.id, m.filename, m.file_type, m.file_size, m.material_type,
                   m.status, m.chunk_count, m.error_message, m.created_at
            FROM materials m
            WHERE m.org_id = (SELECT org_id FROM users WHERE id = $1)
            ORDER BY m.created_at DESC
            """,
            user_id
        )
        return [dict(row) for row in rows]


async def get_material(material_id: int, user_id: int) -> Optional[dict]:
    """Get a material by ID (scoped to user's org)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM materials
            WHERE id = $1 AND org_id = (SELECT org_id FROM users WHERE id = $2)
            """,
            material_id, user_id
        )
        return dict(row) if row else None


async def delete_material(material_id: int, user_id: int) -> Optional[str]:
    """Delete a material and return its storage key for R2 cleanup (org-scoped)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            DELETE FROM materials
            WHERE id = $1 AND org_id = (SELECT org_id FROM users WHERE id = $2)
            RETURNING storage_key
            """,
            material_id, user_id
        )
        return row['storage_key'] if row else None


async def save_chunks(
    material_id: int,
    user_id: int,
    chunks: list[dict],
) -> int:
    """Save chunks with embeddings. Returns count saved."""
    async with _pool.acquire() as conn:
        org_id = await conn.fetchval("SELECT org_id FROM users WHERE id = $1", user_id)
        for i, chunk in enumerate(chunks):
            # Convert embedding list to pgvector format
            embedding = chunk['embedding']
            embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'

            await conn.execute(
                """
                INSERT INTO material_chunks (material_id, user_id, org_id, chunk_index, content, embedding, section_title, material_type)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8)
                """,
                material_id, user_id, org_id, i, chunk['content'], embedding_str,
                chunk.get('section_title'), chunk.get('material_type')
            )

        return len(chunks)


async def vector_search(
    user_id: int,
    query_embedding: list[float],
    limit: int = 5
) -> list[dict]:
    """Search for similar chunks using vector similarity (org-scoped)."""
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
            WHERE org_id = (SELECT org_id FROM users WHERE id = $1)
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
