"""
test_embeddings.py - Tests for embeddings service.

Tests for the EmbeddingService class that generates vector embeddings
using OpenAI's API.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestEmbedText:
    """Tests for embed_text method."""

    @pytest.mark.asyncio
    async def test_embed_text_normal_case(self):
        """embed_text returns embedding vector for normal text."""
        from services.embeddings import EmbeddingService

        # Create mock response with embedding data
        mock_embedding = [0.1] * 1536  # 1536-dimensional vector
        mock_data_item = MagicMock()
        mock_data_item.embedding = mock_embedding

        mock_response = MagicMock()
        mock_response.data = [mock_data_item]

        # Mock the OpenAI client
        mock_client = AsyncMock()
        mock_client.embeddings.create.return_value = mock_response

        with patch("services.embeddings.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="test-key")
            with patch("services.embeddings.openai.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = EmbeddingService()
                result = await service.embed_text("Hello, world!")

        assert result == mock_embedding
        assert len(result) == 1536
        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input="Hello, world!"
        )

    @pytest.mark.asyncio
    async def test_embed_text_truncation(self):
        """embed_text truncates text longer than MAX_CHARS."""
        from services.embeddings import EmbeddingService

        # Create text longer than MAX_CHARS (32000)
        long_text = "a" * 35000

        mock_embedding = [0.1] * 1536
        mock_data_item = MagicMock()
        mock_data_item.embedding = mock_embedding

        mock_response = MagicMock()
        mock_response.data = [mock_data_item]

        mock_client = AsyncMock()
        mock_client.embeddings.create.return_value = mock_response

        with patch("services.embeddings.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="test-key")
            with patch("services.embeddings.openai.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = EmbeddingService()
                result = await service.embed_text(long_text)

        assert result == mock_embedding
        # Verify that the text was truncated to MAX_CHARS (32000)
        call_args = mock_client.embeddings.create.call_args
        assert len(call_args.kwargs["input"]) == 32000


class TestEmbedBatch:
    """Tests for embed_batch method."""

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list(self):
        """embed_batch returns empty list for empty input."""
        from services.embeddings import EmbeddingService

        with patch("services.embeddings.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="test-key")
            with patch("services.embeddings.openai.AsyncOpenAI"):
                service = EmbeddingService()
                result = await service.embed_batch([])

        assert result == []

    @pytest.mark.asyncio
    async def test_embed_batch_single_batch(self):
        """embed_batch processes single batch of texts."""
        from services.embeddings import EmbeddingService

        texts = ["text1", "text2", "text3"]
        mock_embeddings = [[0.1] * 1536, [0.2] * 1536, [0.3] * 1536]

        # Create mock response data items
        mock_data_items = []
        for i, emb in enumerate(mock_embeddings):
            item = MagicMock()
            item.embedding = emb
            item.index = i
            mock_data_items.append(item)

        mock_response = MagicMock()
        mock_response.data = mock_data_items

        mock_client = AsyncMock()
        mock_client.embeddings.create.return_value = mock_response

        with patch("services.embeddings.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="test-key")
            with patch("services.embeddings.openai.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = EmbeddingService()
                result = await service.embed_batch(texts)

        assert len(result) == 3
        assert result[0] == mock_embeddings[0]
        assert result[1] == mock_embeddings[1]
        assert result[2] == mock_embeddings[2]
        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=texts
        )

    @pytest.mark.asyncio
    async def test_embed_batch_multiple_batches(self):
        """embed_batch processes multiple batches correctly."""
        from services.embeddings import EmbeddingService

        # 5 texts with batch_size=2 should create 3 API calls
        texts = ["text1", "text2", "text3", "text4", "text5"]
        batch_size = 2

        # Mock embeddings for each batch
        def create_batch_response(batch_texts, start_index):
            """Helper to create mock response for a batch."""
            mock_data_items = []
            for i, _ in enumerate(batch_texts):
                item = MagicMock()
                item.embedding = [float(start_index + i)] * 1536
                item.index = i
                mock_data_items.append(item)

            mock_response = MagicMock()
            mock_response.data = mock_data_items
            return mock_response

        # Create responses for 3 batches
        responses = [
            create_batch_response(["text1", "text2"], 0),
            create_batch_response(["text3", "text4"], 2),
            create_batch_response(["text5"], 4),
        ]

        mock_client = AsyncMock()
        mock_client.embeddings.create.side_effect = responses

        with patch("services.embeddings.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="test-key")
            with patch("services.embeddings.openai.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = EmbeddingService()
                result = await service.embed_batch(texts, batch_size=batch_size)

        assert len(result) == 5
        assert result[0][0] == 0.0
        assert result[1][0] == 1.0
        assert result[2][0] == 2.0
        assert result[3][0] == 3.0
        assert result[4][0] == 4.0
        assert mock_client.embeddings.create.call_count == 3

    @pytest.mark.asyncio
    async def test_embed_batch_sorts_by_index(self):
        """embed_batch sorts response data by index to maintain order."""
        from services.embeddings import EmbeddingService

        texts = ["text1", "text2", "text3"]

        # Create mock data items in WRONG order
        mock_data_items = []
        # Return them out of order: index 2, 0, 1
        for idx, emb_value in [(2, 0.3), (0, 0.1), (1, 0.2)]:
            item = MagicMock()
            item.embedding = [emb_value] * 1536
            item.index = idx
            mock_data_items.append(item)

        mock_response = MagicMock()
        mock_response.data = mock_data_items

        mock_client = AsyncMock()
        mock_client.embeddings.create.return_value = mock_response

        with patch("services.embeddings.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="test-key")
            with patch("services.embeddings.openai.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = EmbeddingService()
                result = await service.embed_batch(texts)

        # Verify embeddings are returned in correct order (by index)
        assert len(result) == 3
        assert result[0][0] == 0.1  # index 0
        assert result[1][0] == 0.2  # index 1
        assert result[2][0] == 0.3  # index 2

    @pytest.mark.asyncio
    async def test_embed_batch_truncates_long_texts(self):
        """embed_batch truncates texts longer than MAX_CHARS."""
        from services.embeddings import EmbeddingService

        # Create texts with one longer than MAX_CHARS
        texts = [
            "short text",
            "a" * 35000,  # Longer than MAX_CHARS (32000)
            "another short text"
        ]

        mock_data_items = []
        for i in range(3):
            item = MagicMock()
            item.embedding = [float(i)] * 1536
            item.index = i
            mock_data_items.append(item)

        mock_response = MagicMock()
        mock_response.data = mock_data_items

        mock_client = AsyncMock()
        mock_client.embeddings.create.return_value = mock_response

        with patch("services.embeddings.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="test-key")
            with patch("services.embeddings.openai.AsyncOpenAI") as mock_openai:
                mock_openai.return_value = mock_client

                service = EmbeddingService()
                result = await service.embed_batch(texts)

        assert len(result) == 3
        # Verify that the long text was truncated
        call_args = mock_client.embeddings.create.call_args
        batch_input = call_args.kwargs["input"]
        assert len(batch_input[0]) == len("short text")
        assert len(batch_input[1]) == 32000  # Truncated to MAX_CHARS
        assert len(batch_input[2]) == len("another short text")
