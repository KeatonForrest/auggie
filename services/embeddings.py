"""embeddings.py - Generate vector embeddings using OpenAI."""

import openai

from config import get_settings


class EmbeddingService:
    """Service for generating text embeddings."""

    MODEL = "text-embedding-3-small"
    DIMENSIONS = 1536
    MAX_TOKENS = 8000  # Model limit
    MAX_CHARS = 32000  # Rough char limit (~4 chars per token)

    def __init__(self):
        settings = get_settings()
        self.client = openai.OpenAI(api_key=settings.openai_api_key)

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed (will be truncated if too long)

        Returns:
            1536-dimensional embedding vector
        """
        # Truncate if too long
        if len(text) > self.MAX_CHARS:
            text = text[:self.MAX_CHARS]

        response = self.client.embeddings.create(
            model=self.MODEL,
            input=text
        )

        return response.data[0].embedding

    def embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        More efficient than calling embed_text in a loop.
        Handles batching automatically for large lists.

        Args:
            texts: List of texts to embed
            batch_size: Max texts per API call (default 100)

        Returns:
            List of embedding vectors in same order as input
        """
        if not texts:
            return []

        # Truncate each text
        texts = [t[:self.MAX_CHARS] for t in texts]

        all_embeddings = []

        # Process in batches
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            response = self.client.embeddings.create(
                model=self.MODEL,
                input=batch
            )

            # Sort by index to maintain order (API may return out of order)
            sorted_data = sorted(response.data, key=lambda x: x.index)
            batch_embeddings = [item.embedding for item in sorted_data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
