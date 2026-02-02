import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.retrieval import RetrievalService


class TestRetrievalService:
    """Test suite for RetrievalService"""

    @pytest.fixture
    def mock_embedding_service(self):
        """Mock EmbeddingService"""
        with patch('services.retrieval.EmbeddingService') as mock:
            mock_instance = MagicMock()
            mock_instance.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])
            mock.return_value = mock_instance
            yield mock

    @pytest.fixture
    def retrieval_service(self, mock_embedding_service):
        """Create RetrievalService instance with mocked dependencies"""
        return RetrievalService()

    @pytest.mark.asyncio
    async def test_get_relevant_context_success_with_all_params(self, retrieval_service):
        """Test get_relevant_context with all parameters provided"""
        chunks = [
            {
                'content': 'Test content 1',
                'similarity': 0.8,
                'material_type': 'case_study',
                'section_title': 'Introduction'
            },
            {
                'content': 'Test content 2',
                'similarity': 0.7,
                'material_type': 'whitepaper',
                'section_title': 'Conclusion'
            }
        ]

        with patch('services.retrieval.database') as mock_db:
            mock_db.vector_search = AsyncMock(return_value=chunks)

            result = await retrieval_service.get_relevant_context(
                user_id='user123',
                company_name='Acme Corp',
                company_description='A leading software company',
                industry='Technology',
                limit=5,
                min_similarity=0.3
            )

            # Verify database was called with correct params
            mock_db.vector_search.assert_called_once_with(
                user_id='user123',
                query_embedding=[0.1, 0.2, 0.3],
                limit=5
            )

            # Verify result contains formatted chunks
            assert '[From: Case Study - Introduction]' in result
            assert 'Test content 1' in result
            assert '[From: Whitepaper - Conclusion]' in result
            assert 'Test content 2' in result
            assert '---' in result

    @pytest.mark.asyncio
    async def test_get_relevant_context_company_name_only(self, retrieval_service):
        """Test get_relevant_context with only company_name"""
        chunks = [
            {
                'content': 'Test content',
                'similarity': 0.9,
                'material_type': 'blog_post',
                'section_title': 'Overview'
            }
        ]

        with patch('services.retrieval.database') as mock_db:
            mock_db.vector_search = AsyncMock(return_value=chunks)

            result = await retrieval_service.get_relevant_context(
                user_id='user456',
                company_name='Test Company'
            )

            # Verify embedding was created with just company name
            retrieval_service.embeddings.embed_text.assert_called_once_with('Test Company')

            assert 'Test content' in result
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_relevant_context_no_chunks_returns_empty(self, retrieval_service):
        """Test get_relevant_context returns empty string when no chunks found"""
        with patch('services.retrieval.database') as mock_db:
            mock_db.vector_search = AsyncMock(return_value=[])

            result = await retrieval_service.get_relevant_context(
                user_id='user789',
                company_name='Empty Corp'
            )

            assert result == ""

    @pytest.mark.asyncio
    async def test_get_relevant_context_below_threshold_returns_empty(self, retrieval_service):
        """Test get_relevant_context returns empty string when all chunks below similarity threshold"""
        chunks = [
            {
                'content': 'Low similarity content',
                'similarity': 0.2,
                'material_type': 'document',
                'section_title': 'Section'
            },
            {
                'content': 'Another low similarity',
                'similarity': 0.1,
                'material_type': 'guide',
                'section_title': 'Chapter'
            }
        ]

        with patch('services.retrieval.database') as mock_db:
            mock_db.vector_search = AsyncMock(return_value=chunks)

            result = await retrieval_service.get_relevant_context(
                user_id='user999',
                company_name='Low Match Corp',
                min_similarity=0.3
            )

            assert result == ""

    @pytest.mark.asyncio
    async def test_get_relevant_context_description_truncated_to_500(self, retrieval_service):
        """Test that company_description is truncated to 500 characters"""
        long_description = 'A' * 600  # 600 character string
        chunks = [
            {
                'content': 'Test',
                'similarity': 0.8,
                'material_type': 'doc',
                'section_title': 'Title'
            }
        ]

        with patch('services.retrieval.database') as mock_db:
            mock_db.vector_search = AsyncMock(return_value=chunks)

            await retrieval_service.get_relevant_context(
                user_id='user111',
                company_name='BigDesc Corp',
                company_description=long_description
            )

            # Verify the query was truncated
            call_args = retrieval_service.embeddings.embed_text.call_args[0][0]
            # Query should be "BigDesc Corp " + first 500 chars of description
            expected_query = f"BigDesc Corp {long_description[:500]}"
            assert call_args == expected_query

    def test_format_for_prompt_with_material_type_and_section_title(self, retrieval_service):
        """Test _format_for_prompt with both material_type and section_title"""
        chunks = [
            {
                'content': 'Content here',
                'material_type': 'case_study',
                'section_title': 'Introduction'
            }
        ]

        result = retrieval_service._format_for_prompt(chunks)

        assert '[From: Case Study - Introduction]' in result
        assert 'Content here' in result

    def test_format_for_prompt_without_material_type_or_section_title(self, retrieval_service):
        """Test _format_for_prompt falls back to 'Company Material' when fields missing"""
        chunks = [
            {
                'content': 'Generic content'
            }
        ]

        result = retrieval_service._format_for_prompt(chunks)

        assert '[From: Company Material]' in result
        assert 'Generic content' in result

    def test_format_for_prompt_material_type_formatting(self, retrieval_service):
        """Test that material_type is properly formatted (underscores to spaces, title case)"""
        chunks = [
            {
                'content': 'Test content',
                'material_type': 'case_study',
                'section_title': 'Overview'
            },
            {
                'content': 'Another test',
                'material_type': 'white_paper',
                'section_title': 'Summary'
            }
        ]

        result = retrieval_service._format_for_prompt(chunks)

        assert 'Case Study' in result
        assert 'White Paper' in result
        assert 'case_study' not in result
        assert 'white_paper' not in result

    def test_format_for_prompt_multiple_chunks_joined_with_separator(self, retrieval_service):
        """Test that multiple chunks are joined with --- separator"""
        chunks = [
            {
                'content': 'First chunk',
                'material_type': 'doc1',
                'section_title': 'Section 1'
            },
            {
                'content': 'Second chunk',
                'material_type': 'doc2',
                'section_title': 'Section 2'
            },
            {
                'content': 'Third chunk',
                'material_type': 'doc3',
                'section_title': 'Section 3'
            }
        ]

        result = retrieval_service._format_for_prompt(chunks)

        # Check all content is present
        assert 'First chunk' in result
        assert 'Second chunk' in result
        assert 'Third chunk' in result

        # Check separator is used between chunks
        separator_count = result.count('\n\n---\n\n')
        assert separator_count == 2  # 3 chunks means 2 separators


