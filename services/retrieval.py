"""retrieval.py - Retrieve relevant materials for research generation."""

from typing import Optional

import database
from services.embeddings import EmbeddingService


class RetrievalService:
    """Service for retrieving relevant material chunks."""

    def __init__(self):
        self.embeddings = EmbeddingService()

    async def get_relevant_context(
        self,
        user_id: int,
        company_name: str,
        company_description: str = "",
        industry: str = "",
        limit: int = 5,
        min_similarity: float = 0.3
    ) -> str:
        """Retrieve relevant material chunks for a prospect.

        Args:
            user_id: User ID
            company_name: Prospect company name
            company_description: Brief description of prospect (e.g., from homepage)
            industry: Prospect's industry if known
            limit: Max chunks to retrieve
            min_similarity: Minimum similarity threshold (0-1)

        Returns:
            Formatted string of relevant materials for prompt injection,
            or empty string if no relevant materials found
        """
        # Build search query from prospect info
        query_parts = [company_name]
        if company_description:
            # Take first 500 chars of description
            query_parts.append(company_description[:500])
        if industry:
            query_parts.append(industry)

        query = " ".join(query_parts)

        # Generate query embedding
        query_embedding = await self.embeddings.embed_text(query)

        # Vector search
        chunks = await database.vector_search(
            user_id=user_id,
            query_embedding=query_embedding,
            limit=limit
        )

        if not chunks:
            return ""

        # Filter by similarity threshold
        relevant_chunks = [
            c for c in chunks
            if c.get('similarity', 0) >= min_similarity
        ]

        if not relevant_chunks:
            return ""

        # Format for prompt
        return self._format_for_prompt(relevant_chunks)

    def _format_for_prompt(self, chunks: list[dict]) -> str:
        """Format retrieved chunks for injection into Claude prompt.

        Args:
            chunks: List of chunk dicts with content, material_type, section_title, similarity

        Returns:
            Formatted string ready for prompt injection
        """
        sections = []

        for chunk in chunks:
            # Build header from available metadata
            header_parts = []

            material_type = chunk.get('material_type')
            if material_type:
                # Format: case_study -> Case Study
                header_parts.append(material_type.replace('_', ' ').title())

            section_title = chunk.get('section_title')
            if section_title:
                header_parts.append(section_title)

            header = " - ".join(header_parts) if header_parts else "Company Material"

            # Format the chunk
            content = chunk['content'].strip()
            sections.append(f"[From: {header}]\n{content}")

        return "\n\n---\n\n".join(sections)


async def has_materials(user_id: int) -> bool:
    """Check if user has any ready materials.

    Args:
        user_id: User ID to check

    Returns:
        True if user has at least one material with status 'ready'
    """
    materials = await database.get_user_materials(user_id)
    return any(m['status'] == 'ready' for m in materials)
