"""materials.py - Material upload and processing pipeline."""

import asyncio
import functools
from typing import BinaryIO
import logging

import database
from services.storage import R2Storage
from services.parser import DocumentParser, get_file_type
from services.chunking import ChunkingService
from services.embeddings import EmbeddingService

logger = logging.getLogger(__name__)


class MaterialsService:
    """Service for managing material uploads and processing."""

    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    SUPPORTED_TYPES = {'pdf', 'docx', 'pptx', 'txt', 'md'}

    def __init__(self):
        self.storage = R2Storage()
        self.parser = DocumentParser()
        self.chunking = ChunkingService()
        self.embeddings = EmbeddingService()

    async def upload_material(
        self,
        user_id: int,
        file: BinaryIO,
        filename: str,
        material_type: str = "other"
    ) -> dict:
        """Upload a material file and start processing.

        Args:
            user_id: User ID
            file: File object (from upload)
            filename: Original filename
            material_type: Classification (case_study, battle_card, product_doc, sales_deck, other)

        Returns:
            Material record dict

        Raises:
            ValueError: If file type not supported or file too large
        """
        # Validate file type
        file_type = get_file_type(filename)
        if file_type not in self.SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported file type: {file_type}. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_TYPES))}"
            )

        # Read file content to check size
        file_bytes = file.read()
        file_size = len(file_bytes)

        if file_size > self.MAX_FILE_SIZE:
            max_mb = self.MAX_FILE_SIZE // 1024 // 1024
            raise ValueError(f"File too large. Maximum size is {max_mb}MB")

        if file_size == 0:
            raise ValueError("File is empty")

        # Upload to R2
        file.seek(0)  # Reset file pointer
        loop = asyncio.get_event_loop()
        storage_key = await loop.run_in_executor(
            None, functools.partial(self.storage.upload_file, file, user_id, filename)
        )

        # Create database record
        material = await database.create_material(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            storage_key=storage_key,
            material_type=material_type
        )

        # Process in background
        # Note: In production, you might want to use a proper job queue
        asyncio.create_task(
            self._process_material_safe(
                material['id'], user_id, file_bytes, file_type, material_type
            )
        )

        return material

    async def _process_material_safe(
        self,
        material_id: int,
        user_id: int,
        file_bytes: bytes,
        file_type: str,
        material_type: str
    ) -> None:
        """Wrapper for process_material that catches exceptions."""
        try:
            await self.process_material(
                material_id, user_id, file_bytes, file_type, material_type
            )
        except Exception as e:
            logger.exception(f"Failed to process material {material_id}: {e}")
            await database.update_material_status(
                material_id, 'failed',
                error_message=str(e)[:500]
            )

    async def process_material(
        self,
        material_id: int,
        user_id: int,
        file_bytes: bytes,
        file_type: str,
        material_type: str
    ) -> None:
        """Process an uploaded material: parse, chunk, embed, store.

        Args:
            material_id: Material record ID
            user_id: User ID
            file_bytes: Raw file content
            file_type: File extension
            material_type: Classification
        """
        # Update status to processing
        await database.update_material_status(material_id, 'processing')

        # Step 1: Parse document to extract text
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None, functools.partial(self.parser.parse, file_bytes, file_type)
        )

        if not text or not text.strip():
            await database.update_material_status(
                material_id, 'failed',
                error_message="Could not extract text from document"
            )
            return

        logger.info(f"Material {material_id}: Extracted {len(text)} chars")

        # Step 2: Chunk document
        chunks = self.chunking.chunk_document(text, material_type)

        if not chunks:
            await database.update_material_status(
                material_id, 'failed',
                error_message="Document too short to process"
            )
            return

        logger.info(f"Material {material_id}: Created {len(chunks)} chunks")

        # Step 3: Generate embeddings (batch for efficiency)
        chunk_texts = [c.content for c in chunks]
        embeddings = await self.embeddings.embed_batch(chunk_texts)

        logger.info(f"Material {material_id}: Generated {len(embeddings)} embeddings")

        # Step 4: Prepare chunk records
        chunk_records = [
            {
                'content': chunk.content,
                'embedding': embedding,
                'section_title': chunk.section_title,
                'material_type': material_type
            }
            for chunk, embedding in zip(chunks, embeddings)
        ]

        # Step 5: Save chunks to database
        chunk_count = await database.save_chunks(material_id, user_id, chunk_records)

        # Step 6: Update status to ready
        await database.update_material_status(
            material_id, 'ready',
            chunk_count=chunk_count
        )

        logger.info(f"Material {material_id}: Processing complete, {chunk_count} chunks saved")

    async def delete_material(self, material_id: int, user_id: int) -> bool:
        """Delete a material and its associated data.

        Args:
            material_id: Material ID to delete
            user_id: User ID (for authorization)

        Returns:
            True if deleted, False if not found
        """
        # Delete from database (cascades to chunks)
        storage_key = await database.delete_material(material_id, user_id)

        if storage_key:
            # Delete from R2
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, functools.partial(self.storage.delete_file, storage_key)
                )
            except Exception as e:
                # Log but don't fail - file might already be gone
                logger.warning(f"Failed to delete R2 file {storage_key}: {e}")
            return True

        return False

    async def reprocess_material(self, material_id: int, user_id: int) -> bool:
        """Reprocess a failed material.

        Args:
            material_id: Material ID to reprocess
            user_id: User ID (for authorization)

        Returns:
            True if reprocessing started, False if material not found
        """
        material = await database.get_material(material_id, user_id)
        if not material:
            return False

        # Delete existing chunks
        await database.delete_chunks_for_material(material_id)

        # Download file from R2
        loop = asyncio.get_event_loop()
        file_bytes = await loop.run_in_executor(
            None, functools.partial(self.storage.download_file, material['storage_key'])
        )

        # Reprocess
        asyncio.create_task(
            self._process_material_safe(
                material_id,
                user_id,
                file_bytes,
                material['file_type'],
                material['material_type']
            )
        )

        return True
