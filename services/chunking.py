"""chunking.py - Split documents into semantic chunks for embedding."""

import re
from typing import Optional
from dataclasses import dataclass


@dataclass
class Chunk:
    """A document chunk with metadata."""
    index: int
    content: str
    section_title: Optional[str] = None


class ChunkingService:
    """Service for splitting documents into chunks suitable for embedding."""

    # Target ~500 tokens per chunk (roughly 2000 chars)
    DEFAULT_CHUNK_SIZE = 2000
    DEFAULT_OVERLAP = 200
    MIN_CHUNK_SIZE = 100  # Don't create tiny chunks

    def chunk_document(
        self,
        text: str,
        material_type: str = "other",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
    ) -> list[Chunk]:
        """Split document into chunks.

        Args:
            text: Full document text
            material_type: Type of material (affects chunking strategy)
            chunk_size: Target characters per chunk
            overlap: Character overlap between chunks

        Returns:
            List of Chunk objects
        """
        if not text or not text.strip():
            return []

        # Clean up the text
        text = self._clean_text(text)

        # Try semantic chunking first (by headers/sections)
        chunks = self._chunk_by_sections(text, chunk_size)

        # If no clear sections, fall back to sliding window
        if len(chunks) <= 1 and len(text) > chunk_size:
            chunks = self._chunk_sliding_window(text, chunk_size, overlap)

        # Filter out tiny chunks
        chunks = [c for c in chunks if len(c.content.strip()) >= self.MIN_CHUNK_SIZE]

        # Re-index after filtering
        for i, chunk in enumerate(chunks):
            chunk.index = i

        return chunks

    def _clean_text(self, text: str) -> str:
        """Clean up text for better chunking."""
        # Normalize whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        # Remove very long strings of special characters (often artifacts)
        text = re.sub(r'[_\-=]{10,}', '', text)
        return text.strip()

    def _chunk_by_sections(self, text: str, max_chunk_size: int) -> list[Chunk]:
        """Chunk by markdown headers or document sections."""
        # Split on common section patterns:
        # - Markdown headers (## Header)
        # - Slide markers ([Slide N])
        # - Page markers ([Page N])
        # - All-caps headers followed by newline
        section_pattern = r'\n(?=#{1,3}\s|\[(?:Slide|Page)\s+\d+\]|[A-Z][A-Z\s]{5,}:\s*\n)'
        sections = re.split(section_pattern, text)

        chunks = []
        current_section_title = None

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Extract section title if present
            title_match = re.match(
                r'^(#{1,3}\s*(.+?)(?:\n|$)|\[(?:Slide|Page)\s+\d+\]|([A-Z][A-Z\s]{5,}):)',
                section
            )
            if title_match:
                # Get the title text from whichever group matched
                current_section_title = (
                    title_match.group(2) or
                    title_match.group(1) or
                    title_match.group(3) or
                    ""
                ).strip()

            # If section is too large, split it further
            if len(section) > max_chunk_size:
                sub_chunks = self._chunk_sliding_window(
                    section, max_chunk_size, self.DEFAULT_OVERLAP
                )
                for sub_chunk in sub_chunks:
                    sub_chunk.section_title = current_section_title
                    chunks.append(sub_chunk)
            else:
                chunks.append(Chunk(
                    index=len(chunks),
                    content=section,
                    section_title=current_section_title
                ))

        return chunks

    def _chunk_sliding_window(
        self,
        text: str,
        chunk_size: int,
        overlap: int
    ) -> list[Chunk]:
        """Chunk using sliding window with sentence boundaries."""
        # Split into sentences (simple approach)
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_length = len(sentence)

            # If adding this sentence exceeds chunk size, save current chunk
            if current_length + sentence_length > chunk_size and current_chunk:
                chunk_text = ' '.join(current_chunk)
                chunks.append(Chunk(
                    index=len(chunks),
                    content=chunk_text
                ))

                # Keep overlap (last few sentences that fit)
                overlap_sentences = []
                overlap_length = 0
                for s in reversed(current_chunk):
                    if overlap_length + len(s) > overlap:
                        break
                    overlap_sentences.insert(0, s)
                    overlap_length += len(s) + 1  # +1 for space

                current_chunk = overlap_sentences
                current_length = overlap_length

            current_chunk.append(sentence)
            current_length += sentence_length + 1  # +1 for space

        # Don't forget the last chunk
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunks.append(Chunk(
                index=len(chunks),
                content=chunk_text
            ))

        return chunks
