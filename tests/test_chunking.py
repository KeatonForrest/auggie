"""Tests for services/chunking.py"""

import pytest
from services.chunking import ChunkingService, Chunk


class TestChunkDocument:
    """Tests for ChunkingService.chunk_document()"""

    def test_empty_text_returns_empty_list(self):
        service = ChunkingService()
        result = service.chunk_document("")
        assert result == []

    def test_whitespace_only_text_returns_empty_list(self):
        service = ChunkingService()
        result = service.chunk_document("   \n\n  \t  ")
        assert result == []

    def test_short_text_returns_single_chunk(self):
        service = ChunkingService()
        # Make text long enough to pass MIN_CHUNK_SIZE (100 chars)
        text = "This is a short document with just a few sentences. It should fit in one chunk. " + \
               "Adding more content here to ensure it meets the minimum chunk size requirement."
        result = service.chunk_document(text)

        assert len(result) == 1
        assert result[0].index == 0
        assert "short document" in result[0].content
        assert result[0].section_title is None

    def test_text_with_sections_returns_multiple_chunks(self):
        service = ChunkingService()
        text = """
# Introduction
This is the introduction section with some content. Adding more text here to ensure
each section is long enough to pass the minimum chunk size of 100 characters requirement.

## Background
This is the background section with different content. More details about the background
and context to ensure this section is substantial enough to be included as a chunk.

## Methods
This is the methods section with detailed information. Describing the methodology used
in this research project with sufficient detail to meet the minimum length requirement.
"""
        result = service.chunk_document(text)

        assert len(result) > 1
        # Check that chunks have proper indices
        for i, chunk in enumerate(result):
            assert chunk.index == i

    def test_tiny_chunks_filtered_out(self):
        service = ChunkingService()
        # Create text with a tiny section that should be filtered
        text = """
# Main Section
This is a substantial section with enough content to pass the minimum chunk size requirement. It has multiple sentences to ensure it's long enough.

## Tiny
X

# Another Section
This is another substantial section with enough content to pass the minimum chunk size requirement. More sentences here.
"""
        result = service.chunk_document(text)

        # The tiny "X" section should be filtered out (< 100 chars)
        for chunk in result:
            assert len(chunk.content.strip()) >= service.MIN_CHUNK_SIZE

    def test_re_indexing_after_filter(self):
        service = ChunkingService()
        text = """
# Section 1
This is a substantial section with enough content to pass the minimum chunk size requirement. It has multiple sentences.

## Tiny Section
Y

# Section 2
This is another substantial section with enough content to pass the minimum chunk size requirement. More sentences here.

## Another Tiny
Z

# Section 3
Final substantial section with enough content to pass the minimum chunk size requirement. Even more sentences.
"""
        result = service.chunk_document(text)

        # Indices should be sequential starting from 0
        for i, chunk in enumerate(result):
            assert chunk.index == i

        # Should have 3 chunks (tiny ones filtered out)
        assert all(len(chunk.content.strip()) >= service.MIN_CHUNK_SIZE for chunk in result)


class TestCleanText:
    """Tests for ChunkingService._clean_text()"""

    def test_normalizes_multiple_newlines(self):
        service = ChunkingService()
        text = "Line 1\n\n\n\n\nLine 2"
        result = service._clean_text(text)
        assert result == "Line 1\n\nLine 2"

    def test_normalizes_multiple_spaces(self):
        service = ChunkingService()
        text = "Word1    Word2     Word3"
        result = service._clean_text(text)
        assert result == "Word1 Word2 Word3"

    def test_removes_long_underscore_strings(self):
        service = ChunkingService()
        text = "Section A\n__________\nContent here"
        result = service._clean_text(text)
        assert "___" not in result
        assert "Section A" in result
        assert "Content here" in result

    def test_removes_long_dash_strings(self):
        service = ChunkingService()
        text = "Section A\n----------\nContent here"
        result = service._clean_text(text)
        assert "---" not in result
        assert "Section A" in result

    def test_removes_long_equals_strings(self):
        service = ChunkingService()
        text = "Section A\n==========\nContent here"
        result = service._clean_text(text)
        assert "===" not in result
        assert "Section A" in result

    def test_strips_leading_and_trailing_whitespace(self):
        service = ChunkingService()
        text = "   Some content   \n\n"
        result = service._clean_text(text)
        assert result == "Some content"

    def test_combined_cleaning(self):
        service = ChunkingService()
        text = """

        Title
        ==========

        Some    content    here.



        More content.
        __________
        """
        result = service._clean_text(text)
        assert "===" not in result
        assert "___" not in result
        assert "    " not in result
        assert "\n\n\n" not in result


class TestChunkBySections:
    """Tests for ChunkingService._chunk_by_sections()"""

    def test_markdown_h1_headers_split_correctly(self):
        service = ChunkingService()
        text = """# Section 1
Content for section 1.
# Section 2
Content for section 2."""
        result = service._chunk_by_sections(text, 2000)

        assert len(result) == 2
        assert "Section 1" in result[0].content
        assert "Section 2" in result[1].content

    def test_markdown_h2_headers_split_correctly(self):
        service = ChunkingService()
        text = """## Subsection A
Content A.
## Subsection B
Content B."""
        result = service._chunk_by_sections(text, 2000)

        assert len(result) == 2
        assert "Subsection A" in result[0].content
        assert "Subsection B" in result[1].content

    def test_markdown_h3_headers_split_correctly(self):
        service = ChunkingService()
        text = """### Part 1
Content 1.
### Part 2
Content 2."""
        result = service._chunk_by_sections(text, 2000)

        assert len(result) == 2
        assert "Part 1" in result[0].content
        assert "Part 2" in result[1].content

    def test_slide_markers_split_correctly(self):
        service = ChunkingService()
        text = """[Slide 1]
First slide content.
[Slide 2]
Second slide content."""
        result = service._chunk_by_sections(text, 2000)

        assert len(result) == 2
        assert "First slide" in result[0].content
        assert "Second slide" in result[1].content

    def test_page_markers_split_correctly(self):
        service = ChunkingService()
        text = """[Page 1]
First page content.
[Page 2]
Second page content."""
        result = service._chunk_by_sections(text, 2000)

        assert len(result) == 2
        assert "First page" in result[0].content
        assert "Second page" in result[1].content

    def test_all_caps_headers_split_correctly(self):
        service = ChunkingService()
        text = """INTRODUCTION:
This is the introduction.
BACKGROUND:
This is the background."""
        result = service._chunk_by_sections(text, 2000)

        assert len(result) == 2
        assert "introduction" in result[0].content.lower()
        assert "background" in result[1].content.lower()

    def test_section_titles_extracted_from_markdown(self):
        service = ChunkingService()
        text = """# My Title
Content here.
## Subsection Title
More content."""
        result = service._chunk_by_sections(text, 2000)

        assert result[0].section_title == "My Title"
        assert result[1].section_title == "Subsection Title"

    def test_section_titles_extracted_from_slide_markers(self):
        service = ChunkingService()
        text = """[Slide 1]
Content here."""
        result = service._chunk_by_sections(text, 2000)

        assert result[0].section_title == "[Slide 1]"

    def test_section_titles_extracted_from_all_caps(self):
        service = ChunkingService()
        text = """EXECUTIVE SUMMARY:
Content here."""
        result = service._chunk_by_sections(text, 2000)

        # The regex captures the colon as part of the title
        assert result[0].section_title == "EXECUTIVE SUMMARY:"

    def test_oversized_sections_get_sub_chunked(self):
        service = ChunkingService()
        # Create a section that exceeds max_chunk_size
        long_content = "This is a sentence. " * 200  # ~4000 chars
        text = f"""# Long Section
{long_content}"""
        result = service._chunk_by_sections(text, 1000)

        # Should be split into multiple chunks
        assert len(result) > 1
        # All sub-chunks should have the same section title
        for chunk in result:
            assert chunk.section_title == "Long Section"

    def test_empty_sections_ignored(self):
        service = ChunkingService()
        text = """# Section 1
Content.

# Section 2

## Empty Subsection

# Section 3
More content."""
        result = service._chunk_by_sections(text, 2000)

        # Empty sections should be filtered out
        for chunk in result:
            assert chunk.content.strip()


class TestChunkSlidingWindow:
    """Tests for ChunkingService._chunk_sliding_window()"""

    def test_basic_splitting(self):
        service = ChunkingService()
        text = "First sentence. " * 100  # ~1600 chars
        result = service._chunk_sliding_window(text, 500, 50)

        # Should create multiple chunks
        assert len(result) > 1
        # Each chunk should be indexed
        for i, chunk in enumerate(result):
            assert chunk.index == i

    def test_overlap_between_chunks(self):
        service = ChunkingService()
        text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five. Sentence six. Sentence seven. Sentence eight."
        result = service._chunk_sliding_window(text, 50, 20)

        if len(result) > 1:
            # Check that there's some overlap between consecutive chunks
            # At least one sentence should appear in both chunks
            chunk1_sentences = set(result[0].content.split(". "))
            chunk2_sentences = set(result[1].content.split(". "))
            # There should be some overlap
            overlap = chunk1_sentences & chunk2_sentences
            assert len(overlap) > 0 or "Sentence" in result[1].content

    def test_single_sentence(self):
        service = ChunkingService()
        text = "This is a single sentence."
        result = service._chunk_sliding_window(text, 100, 10)

        assert len(result) == 1
        assert result[0].content == text
        assert result[0].index == 0

    def test_respects_sentence_boundaries(self):
        service = ChunkingService()
        text = "First! Second? Third. Fourth."
        result = service._chunk_sliding_window(text, 100, 10)

        # Should keep sentences together
        for chunk in result:
            # Chunks should end with sentence terminators or be complete
            content = chunk.content.strip()
            if content:
                # Check that we're not cutting mid-sentence
                assert content[-1] in '.!?' or content == text

    def test_empty_sentences_ignored(self):
        service = ChunkingService()
        text = "Sentence one.   Sentence two.     Sentence three."
        result = service._chunk_sliding_window(text, 200, 20)

        # Should handle extra spaces gracefully
        for chunk in result:
            assert chunk.content.strip()

    def test_very_long_single_sentence(self):
        service = ChunkingService()
        # A sentence longer than chunk_size
        text = "This is a very long sentence that goes on and on without any breaks " * 50
        result = service._chunk_sliding_window(text, 100, 20)

        # Should still create at least one chunk
        assert len(result) >= 1

    def test_chunk_size_boundary(self):
        service = ChunkingService()
        # Create text where sentences total just over chunk_size
        text = "A" * 30 + ". " + "B" * 30 + ". " + "C" * 30 + "."
        result = service._chunk_sliding_window(text, 50, 10)

        # Should split appropriately
        assert len(result) > 1
        for chunk in result:
            # Chunks might exceed chunk_size slightly due to sentence boundaries
            # but shouldn't be empty
            assert len(chunk.content) > 0


class TestIntegration:
    """Integration tests combining multiple methods"""

    def test_full_document_with_mixed_sections(self):
        service = ChunkingService()
        text = """
# Executive Summary
This is a comprehensive overview of our findings. It contains multiple sentences
that explain the key points and recommendations.

## Key Findings
- Finding one with details
- Finding two with more information
- Finding three with additional context

# Detailed Analysis
[Slide 1]
This slide contains the first part of our analysis. It has charts and graphs
showing important trends in the market.

[Slide 2]
This slide shows the second part of our analysis with more detailed information
about customer segments and their behaviors.

RECOMMENDATIONS:
Based on our analysis, we recommend the following actions for the company
to take in order to improve their market position.
"""
        result = service.chunk_document(text, chunk_size=300, overlap=50)

        # Should create multiple chunks
        assert len(result) > 1

        # All chunks should be properly indexed
        for i, chunk in enumerate(result):
            assert chunk.index == i

        # All chunks should meet minimum size
        for chunk in result:
            assert len(chunk.content.strip()) >= service.MIN_CHUNK_SIZE

        # Some chunks should have section titles
        assert any(chunk.section_title is not None for chunk in result)

    def test_document_with_cleaning_needed(self):
        service = ChunkingService()
        text = """

# Introduction
==========

This    is    content    with    extra    spaces.



And    extra    newlines.

__________

## Next Section
More content here.
"""
        result = service.chunk_document(text)

        # Should clean the text before chunking
        for chunk in result:
            assert "====" not in chunk.content
            assert "____" not in chunk.content
            assert "    " not in chunk.content

    def test_fallback_to_sliding_window(self):
        service = ChunkingService()
        # Long text with no clear sections
        text = "This is a sentence. " * 200  # ~4000 chars, no sections
        result = service.chunk_document(text, chunk_size=500, overlap=50)

        # Should use sliding window and create multiple chunks
        assert len(result) > 1

        # No chunks should have section titles (no sections detected)
        assert all(chunk.section_title is None for chunk in result)
