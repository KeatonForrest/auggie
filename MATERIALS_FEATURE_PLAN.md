# Materials Feature Implementation Plan

Add the ability for users to upload company materials (sales decks, case studies, battle cards) that get intelligently retrieved and injected into research generation.

**Stack:** PostgreSQL + pgvector + Cloudflare R2 + OpenAI Embeddings

---

## Phase 1: Database Setup (pgvector)

### Step 1.1: Enable pgvector extension on Railway

Run this SQL in your Railway PostgreSQL console:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Step 1.2: Add materials tables

Add to `database.py` in `init_database()`:

```sql
-- Materials metadata table
CREATE TABLE IF NOT EXISTS materials (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- File info
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,  -- 'pdf', 'docx', 'pptx', 'txt', 'md'
    file_size INTEGER,
    storage_key TEXT NOT NULL,  -- R2 object key

    -- Classification
    material_type TEXT DEFAULT 'other',  -- 'case_study', 'battle_card', 'product_doc', 'sales_deck', 'other'

    -- Processing
    status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'ready', 'failed'
    chunk_count INTEGER DEFAULT 0,
    error_message TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_materials_user ON materials(user_id);
CREATE INDEX IF NOT EXISTS idx_materials_status ON materials(user_id, status);

-- Chunks with vector embeddings
CREATE TABLE IF NOT EXISTS material_chunks (
    id BIGSERIAL PRIMARY KEY,
    material_id BIGINT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),  -- OpenAI text-embedding-3-small dimension

    -- Metadata for context
    section_title TEXT,
    material_type TEXT,  -- Denormalized for query efficiency

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vector similarity search index (IVFFlat for speed)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
ON material_chunks USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_chunks_user ON material_chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_material ON material_chunks(material_id);
```

---

## Phase 2: Cloudflare R2 Setup

### Step 2.1: Create R2 bucket

1. Go to Cloudflare Dashboard → R2
2. Create bucket: `auggie-materials`
3. Create API token with read/write access
4. Save credentials:
   - `R2_ACCOUNT_ID`
   - `R2_ACCESS_KEY_ID`
   - `R2_SECRET_ACCESS_KEY`
   - `R2_BUCKET_NAME=auggie-materials`

### Step 2.2: Add to config.py

```python
# R2 Storage
r2_account_id: str = ""
r2_access_key_id: str = ""
r2_secret_access_key: str = ""
r2_bucket_name: str = "auggie-materials"

@property
def r2_endpoint_url(self) -> str:
    return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
```

### Step 2.3: Create services/storage.py

```python
"""storage.py - Cloudflare R2 file storage operations."""

import boto3
from botocore.config import Config
from uuid import uuid4
from typing import BinaryIO

from config import get_settings


class R2Storage:
    """Service for storing and retrieving files from Cloudflare R2."""

    def __init__(self):
        settings = get_settings()
        self.client = boto3.client(
            's3',
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=Config(signature_version='s3v4'),
        )
        self.bucket = settings.r2_bucket_name

    def upload_file(self, file: BinaryIO, user_id: int, filename: str) -> str:
        """Upload a file and return the storage key."""
        # Generate unique key: materials/{user_id}/{uuid}_{filename}
        file_id = str(uuid4())[:8]
        key = f"materials/{user_id}/{file_id}_{filename}"

        self.client.upload_fileobj(file, self.bucket, key)
        return key

    def download_file(self, key: str) -> bytes:
        """Download a file by its storage key."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response['Body'].read()

    def delete_file(self, key: str) -> None:
        """Delete a file by its storage key."""
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a temporary download URL."""
        return self.client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': key},
            ExpiresIn=expires_in
        )
```

### Step 2.4: Add to requirements.txt

```
boto3>=1.34.0
```

---

## Phase 3: Document Parsing

### Step 3.1: Create services/parser.py

```python
"""parser.py - Extract text from uploaded documents."""

import io
from typing import Optional
from pathlib import Path

# PDF
from pypdf import PdfReader

# DOCX
from docx import Document as DocxDocument

# PPTX
from pptx import Presentation


class DocumentParser:
    """Service for extracting text from various document formats."""

    SUPPORTED_TYPES = {'pdf', 'docx', 'pptx', 'txt', 'md'}

    def parse(self, file_bytes: bytes, file_type: str) -> str:
        """Extract text from a document.

        Args:
            file_bytes: Raw file content
            file_type: File extension (pdf, docx, pptx, txt, md)

        Returns:
            Extracted text content
        """
        file_type = file_type.lower().lstrip('.')

        if file_type not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported file type: {file_type}")

        if file_type == 'pdf':
            return self._parse_pdf(file_bytes)
        elif file_type == 'docx':
            return self._parse_docx(file_bytes)
        elif file_type == 'pptx':
            return self._parse_pptx(file_bytes)
        elif file_type in ('txt', 'md'):
            return file_bytes.decode('utf-8', errors='ignore')

        return ""

    def _parse_pdf(self, file_bytes: bytes) -> str:
        """Extract text from PDF."""
        reader = PdfReader(io.BytesIO(file_bytes))
        text_parts = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

        return "\n\n".join(text_parts)

    def _parse_docx(self, file_bytes: bytes) -> str:
        """Extract text from DOCX."""
        doc = DocxDocument(io.BytesIO(file_bytes))
        text_parts = []

        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)

        # Also extract from tables
        for table in doc.tables:
            for row in table.rows:
                row_text = ' | '.join(cell.text for cell in row.cells if cell.text.strip())
                if row_text:
                    text_parts.append(row_text)

        return "\n\n".join(text_parts)

    def _parse_pptx(self, file_bytes: bytes) -> str:
        """Extract text from PowerPoint."""
        prs = Presentation(io.BytesIO(file_bytes))
        text_parts = []

        for slide_num, slide in enumerate(prs.slides, 1):
            slide_texts = [f"[Slide {slide_num}]"]

            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    slide_texts.append(shape.text)

            if len(slide_texts) > 1:  # Has content beyond slide number
                text_parts.append("\n".join(slide_texts))

        return "\n\n".join(text_parts)


def get_file_type(filename: str) -> str:
    """Extract file type from filename."""
    return Path(filename).suffix.lower().lstrip('.')
```

### Step 3.2: Add to requirements.txt

```
pypdf>=4.0.0
python-docx>=1.1.0
python-pptx>=0.6.23
```

---

## Phase 4: Chunking Service

### Step 4.1: Create services/chunking.py

```python
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

        # Try semantic chunking first (by headers/sections)
        chunks = self._chunk_by_sections(text, chunk_size)

        # If no clear sections, fall back to sliding window
        if len(chunks) <= 1:
            chunks = self._chunk_sliding_window(text, chunk_size, overlap)

        return chunks

    def _chunk_by_sections(self, text: str, max_chunk_size: int) -> list[Chunk]:
        """Chunk by markdown headers or document sections."""
        # Split on common section patterns
        section_pattern = r'\n(?=#{1,3}\s|(?:^|\n)[A-Z][A-Za-z\s]+:\s*\n|\[Slide \d+\])'
        sections = re.split(section_pattern, text)

        chunks = []
        current_section_title = None

        for i, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue

            # Extract section title if present
            title_match = re.match(r'^(#{1,3}\s*(.+)|([A-Z][A-Za-z\s]+):)', section)
            if title_match:
                current_section_title = (title_match.group(2) or title_match.group(3) or "").strip()

            # If section is too large, split it further
            if len(section) > max_chunk_size:
                sub_chunks = self._chunk_sliding_window(section, max_chunk_size, 200)
                for sub_chunk in sub_chunks:
                    sub_chunk.section_title = current_section_title
                    chunks.append(sub_chunk)
            else:
                chunks.append(Chunk(
                    index=len(chunks),
                    content=section,
                    section_title=current_section_title
                ))

        # Re-index
        for i, chunk in enumerate(chunks):
            chunk.index = i

        return chunks

    def _chunk_sliding_window(
        self,
        text: str,
        chunk_size: int,
        overlap: int
    ) -> list[Chunk]:
        """Chunk using sliding window with sentence boundaries."""
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence_length = len(sentence)

            if current_length + sentence_length > chunk_size and current_chunk:
                # Save current chunk
                chunks.append(Chunk(
                    index=len(chunks),
                    content=' '.join(current_chunk)
                ))

                # Keep overlap (last few sentences)
                overlap_text = ' '.join(current_chunk)
                if len(overlap_text) > overlap:
                    # Find sentences that fit in overlap
                    overlap_sentences = []
                    overlap_length = 0
                    for s in reversed(current_chunk):
                        if overlap_length + len(s) > overlap:
                            break
                        overlap_sentences.insert(0, s)
                        overlap_length += len(s)
                    current_chunk = overlap_sentences
                    current_length = overlap_length
                else:
                    current_chunk = []
                    current_length = 0

            current_chunk.append(sentence)
            current_length += sentence_length

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(Chunk(
                index=len(chunks),
                content=' '.join(current_chunk)
            ))

        return chunks
```

---

## Phase 5: Embeddings Service

### Step 5.1: Create services/embeddings.py

```python
"""embeddings.py - Generate vector embeddings using OpenAI."""

import openai
from typing import Optional

from config import get_settings


class EmbeddingService:
    """Service for generating text embeddings."""

    MODEL = "text-embedding-3-small"
    DIMENSIONS = 1536

    def __init__(self):
        settings = get_settings()
        self.client = openai.OpenAI(api_key=settings.openai_api_key)

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed (max ~8000 tokens)

        Returns:
            1536-dimensional embedding vector
        """
        # Truncate if too long (roughly 8000 tokens = 32000 chars)
        if len(text) > 32000:
            text = text[:32000]

        response = self.client.embeddings.create(
            model=self.MODEL,
            input=text
        )

        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        More efficient than calling embed_text in a loop.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        # Truncate each text
        texts = [t[:32000] for t in texts]

        response = self.client.embeddings.create(
            model=self.MODEL,
            input=texts
        )

        # Sort by index to maintain order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]
```

### Step 5.2: Add to config.py

```python
openai_api_key: str = ""
```

### Step 5.3: Add to requirements.txt

```
openai>=1.0.0
```

---

## Phase 6: Materials Database Operations

### Step 6.1: Add to database.py

```python
# =============================================================================
# Materials Operations
# =============================================================================

async def create_material(
    user_id: int,
    filename: str,
    file_type: str,
    file_size: int,
    storage_key: str,
    material_type: str = "other"
) -> dict:
    """Create a new material record."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO materials (user_id, filename, file_type, file_size, storage_key, material_type)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            user_id, filename, file_type, file_size, storage_key, material_type
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
    """Get all materials for a user."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, filename, file_type, file_size, material_type, status, chunk_count, error_message, created_at
            FROM materials
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id
        )
        return [dict(row) for row in rows]


async def get_material(material_id: int, user_id: int) -> Optional[dict]:
    """Get a material by ID (scoped to user)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM materials WHERE id = $1 AND user_id = $2",
            material_id, user_id
        )
        return dict(row) if row else None


async def delete_material(material_id: int, user_id: int) -> Optional[str]:
    """Delete a material and return its storage key for R2 cleanup."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM materials WHERE id = $1 AND user_id = $2 RETURNING storage_key",
            material_id, user_id
        )
        return row['storage_key'] if row else None


# =============================================================================
# Chunk Operations
# =============================================================================

async def save_chunks(
    material_id: int,
    user_id: int,
    chunks: list[dict],  # [{content, embedding, section_title, material_type}]
) -> int:
    """Save chunks with embeddings. Returns count saved."""
    async with _pool.acquire() as conn:
        # Use COPY for efficiency with many chunks
        records = [
            (material_id, user_id, i, c['content'], c['embedding'], c.get('section_title'), c.get('material_type'))
            for i, c in enumerate(chunks)
        ]

        await conn.executemany(
            """
            INSERT INTO material_chunks (material_id, user_id, chunk_index, content, embedding, section_title, material_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            records
        )

        return len(records)


async def vector_search(
    user_id: int,
    query_embedding: list[float],
    limit: int = 5
) -> list[dict]:
    """Search for similar chunks using vector similarity.

    Args:
        user_id: User ID to scope search
        query_embedding: 1536-dim embedding vector
        limit: Max chunks to return

    Returns:
        List of chunks with similarity scores
    """
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
            WHERE user_id = $1
            ORDER BY embedding <=> $2::vector
            LIMIT $3
            """,
            user_id, embedding_str, limit
        )

        return [dict(row) for row in rows]


async def delete_chunks_for_material(material_id: int) -> None:
    """Delete all chunks for a material."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM material_chunks WHERE material_id = $1",
            material_id
        )
```

---

## Phase 7: Retrieval Service

### Step 7.1: Create services/retrieval.py

```python
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
            company_description: Brief description of prospect
            industry: Prospect's industry
            limit: Max chunks to retrieve
            min_similarity: Minimum similarity threshold

        Returns:
            Formatted string of relevant materials for prompt injection
        """
        # Build search query from prospect info
        query_parts = [company_name]
        if company_description:
            query_parts.append(company_description[:500])
        if industry:
            query_parts.append(industry)

        query = " ".join(query_parts)

        # Generate query embedding
        query_embedding = self.embeddings.embed_text(query)

        # Vector search
        chunks = await database.vector_search(
            user_id=user_id,
            query_embedding=query_embedding,
            limit=limit
        )

        # Filter by similarity threshold
        relevant_chunks = [c for c in chunks if c['similarity'] >= min_similarity]

        if not relevant_chunks:
            return ""

        # Format for prompt
        return self._format_for_prompt(relevant_chunks)

    def _format_for_prompt(self, chunks: list[dict]) -> str:
        """Format retrieved chunks for injection into Claude prompt."""
        sections = []

        for chunk in chunks:
            header_parts = []
            if chunk.get('material_type'):
                header_parts.append(chunk['material_type'].replace('_', ' ').title())
            if chunk.get('section_title'):
                header_parts.append(chunk['section_title'])

            header = " - ".join(header_parts) if header_parts else "Company Material"

            sections.append(f"[From: {header}]\n{chunk['content']}")

        return "\n\n---\n\n".join(sections)
```

---

## Phase 8: Material Processing Pipeline

### Step 8.1: Create services/materials.py

```python
"""materials.py - Material upload and processing pipeline."""

import asyncio
from typing import BinaryIO

import database
from services.storage import R2Storage
from services.parser import DocumentParser, get_file_type
from services.chunking import ChunkingService
from services.embeddings import EmbeddingService


class MaterialsService:
    """Service for managing material uploads and processing."""

    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

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
        """Upload a material file and queue for processing.

        Args:
            user_id: User ID
            file: File object
            filename: Original filename
            material_type: Type classification

        Returns:
            Material record
        """
        # Validate file type
        file_type = get_file_type(filename)
        if file_type not in self.parser.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported file type: {file_type}. Supported: {', '.join(self.parser.SUPPORTED_TYPES)}")

        # Read file content
        file_bytes = file.read()
        file_size = len(file_bytes)

        if file_size > self.MAX_FILE_SIZE:
            raise ValueError(f"File too large. Maximum size is {self.MAX_FILE_SIZE // 1024 // 1024}MB")

        # Upload to R2
        file.seek(0)  # Reset file pointer
        storage_key = self.storage.upload_file(file, user_id, filename)

        # Create database record
        material = await database.create_material(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            storage_key=storage_key,
            material_type=material_type
        )

        # Process in background (or inline for simplicity)
        # For MVP, process inline. Add background jobs later.
        asyncio.create_task(self.process_material(material['id'], user_id, file_bytes, file_type, material_type))

        return material

    async def process_material(
        self,
        material_id: int,
        user_id: int,
        file_bytes: bytes,
        file_type: str,
        material_type: str
    ) -> None:
        """Process an uploaded material: parse, chunk, embed, store."""
        try:
            # Update status
            await database.update_material_status(material_id, 'processing')

            # Parse document
            text = self.parser.parse(file_bytes, file_type)

            if not text.strip():
                await database.update_material_status(
                    material_id, 'failed',
                    error_message="Could not extract text from document"
                )
                return

            # Chunk document
            chunks = self.chunking.chunk_document(text, material_type)

            if not chunks:
                await database.update_material_status(
                    material_id, 'failed',
                    error_message="Document too short to process"
                )
                return

            # Generate embeddings (batch for efficiency)
            chunk_texts = [c.content for c in chunks]
            embeddings = self.embeddings.embed_batch(chunk_texts)

            # Prepare chunk records
            chunk_records = [
                {
                    'content': chunk.content,
                    'embedding': embedding,
                    'section_title': chunk.section_title,
                    'material_type': material_type
                }
                for chunk, embedding in zip(chunks, embeddings)
            ]

            # Save chunks
            chunk_count = await database.save_chunks(material_id, user_id, chunk_records)

            # Update status
            await database.update_material_status(material_id, 'ready', chunk_count=chunk_count)

        except Exception as e:
            await database.update_material_status(
                material_id, 'failed',
                error_message=str(e)[:500]
            )
            raise

    async def delete_material(self, material_id: int, user_id: int) -> bool:
        """Delete a material and its chunks."""
        # Delete from database (cascades to chunks)
        storage_key = await database.delete_material(material_id, user_id)

        if storage_key:
            # Delete from R2
            try:
                self.storage.delete_file(storage_key)
            except Exception:
                pass  # Log but don't fail if R2 delete fails
            return True

        return False
```

---

## Phase 9: Integrate with Claude Service

### Step 9.1: Modify services/claude.py

Update `_build_system_prompt` to accept retrieved materials:

```python
def _build_system_prompt(self, product_context: str, retrieved_materials: str = "") -> str:
    """Build the system prompt defining Claude's research analyst role."""

    base_prompt = f"""You are a sales research analyst creating a targeted research document...

YOUR PRODUCT CONTEXT (the product you are selling):

{product_context}
"""

    # Add materials section if available
    if retrieved_materials:
        base_prompt += f"""

RELEVANT MATERIALS FROM YOUR COMPANY:

The following excerpts from your sales materials are relevant to this prospect. Use them to:
- Reference specific case studies with similar companies or industries
- Pull relevant proof points, metrics, and ROI data
- Identify competitive insights if the prospect uses a competitor
- Suggest specific product capabilities that match their stated needs
- Use customer quotes or testimonials where relevant

{retrieved_materials}

When using these materials:
- Cite the source (e.g., "According to your Acme Corp case study...")
- Prioritize data points and metrics over general claims
- Match case study industries/sizes to the prospect when possible
"""

    base_prompt += """

When analyzing the prospect, specifically look for:
- **Pain point matches**: Does the prospect have problems that align with what your product solves?
...
"""  # Rest of existing prompt

    return base_prompt
```

Update `generate_research_document` signature:

```python
async def generate_research_document(
    self,
    company_url: str,
    scraped: ScrapedContent,
    product_context: str,
    tech_by_domain: Optional[dict[str, TechStack]] = None,
    retrieved_materials: str = "",  # NEW
) -> ResearchDocument:
    """Generate the full Account Research Document using Claude."""
    system_prompt = self._build_system_prompt(product_context, retrieved_materials)
    # ... rest unchanged
```

---

## Phase 10: API Routes

### Step 10.1: Add materials routes to main.py

```python
from fastapi import UploadFile, File, Form
from services.materials import MaterialsService
from services.retrieval import RetrievalService

materials_service = MaterialsService()
retrieval_service = RetrievalService()


@app.get("/materials")
async def materials_page(request: Request, user: dict = Depends(require_auth)):
    """Materials management page."""
    materials = await database.get_user_materials(user['id'])
    return templates.TemplateResponse("materials.html", {
        "request": request,
        "user": user,
        "materials": materials
    })


@app.post("/materials/upload")
async def upload_material(
    file: UploadFile = File(...),
    material_type: str = Form("other"),
    user: dict = Depends(require_auth)
):
    """Upload a new material."""
    try:
        material = await materials_service.upload_material(
            user_id=user['id'],
            file=file.file,
            filename=file.filename,
            material_type=material_type
        )
        return {"success": True, "material": material}
    except ValueError as e:
        return {"success": False, "error": str(e)}


@app.delete("/materials/{material_id}")
async def delete_material(
    material_id: int,
    user: dict = Depends(require_auth)
):
    """Delete a material."""
    deleted = await materials_service.delete_material(material_id, user['id'])
    return {"success": deleted}


@app.get("/api/materials")
async def list_materials(user: dict = Depends(require_auth)):
    """API: List user's materials."""
    materials = await database.get_user_materials(user['id'])
    return {"materials": materials}
```

### Step 10.2: Update research endpoint

```python
@app.post("/research")
async def generate_research(
    request: Request,
    company_url: str = Form(...),
    user: dict = Depends(require_auth),
    user_onboarded: dict = Depends(require_onboarding),
):
    # ... existing scraping code ...

    # NEW: Retrieve relevant materials
    retrieved_materials = ""
    try:
        retrieved_materials = await retrieval_service.get_relevant_context(
            user_id=user['id'],
            company_name=company_name,
            company_description=scraped.homepage[:500] if scraped.homepage else "",
        )
    except Exception as e:
        # Log but don't fail research if retrieval fails
        print(f"Materials retrieval failed: {e}")

    # Generate research document with materials
    doc = await claude_service.generate_research_document(
        company_url=company_url,
        scraped=scraped,
        product_context=user_onboarded['product_context'],
        tech_by_domain=tech_results,
        retrieved_materials=retrieved_materials,  # NEW
    )

    # ... rest unchanged
```

---

## Phase 11: UI Template

### Step 11.1: Create templates/materials.html

```html
{% extends "base.html" %}

{% block content %}
<div class="max-w-4xl mx-auto py-8 px-4">
    <div class="flex justify-between items-center mb-8">
        <div>
            <h1 class="text-2xl font-bold text-gray-900">Sales Materials</h1>
            <p class="text-gray-600 mt-1">Upload case studies, battle cards, and product docs to enhance your research.</p>
        </div>
        <button onclick="openUploadModal()" class="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700">
            Upload Material
        </button>
    </div>

    <!-- Materials List -->
    <div class="bg-white shadow rounded-lg overflow-hidden">
        {% if materials %}
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">File</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Chunks</th>
                    <th class="px-6 py-3"></th>
                </tr>
            </thead>
            <tbody class="divide-y divide-gray-200">
                {% for material in materials %}
                <tr>
                    <td class="px-6 py-4">
                        <div class="flex items-center">
                            <span class="text-2xl mr-3">
                                {% if material.file_type == 'pdf' %}📄{% elif material.file_type == 'docx' %}📝{% elif material.file_type == 'pptx' %}📊{% else %}📁{% endif %}
                            </span>
                            <div>
                                <div class="text-sm font-medium text-gray-900">{{ material.filename }}</div>
                                <div class="text-sm text-gray-500">{{ (material.file_size / 1024) | round }}KB</div>
                            </div>
                        </div>
                    </td>
                    <td class="px-6 py-4">
                        <span class="px-2 py-1 text-xs rounded-full bg-gray-100 text-gray-800">
                            {{ material.material_type | replace('_', ' ') | title }}
                        </span>
                    </td>
                    <td class="px-6 py-4">
                        {% if material.status == 'ready' %}
                        <span class="text-green-600 flex items-center">
                            <svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path></svg>
                            Ready
                        </span>
                        {% elif material.status == 'processing' %}
                        <span class="text-yellow-600 flex items-center">
                            <svg class="animate-spin w-4 h-4 mr-1" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>
                            Processing...
                        </span>
                        {% elif material.status == 'failed' %}
                        <span class="text-red-600 flex items-center" title="{{ material.error_message }}">
                            <svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"></path></svg>
                            Failed
                        </span>
                        {% else %}
                        <span class="text-gray-500">Pending</span>
                        {% endif %}
                    </td>
                    <td class="px-6 py-4 text-sm text-gray-500">
                        {{ material.chunk_count }}
                    </td>
                    <td class="px-6 py-4 text-right">
                        <button onclick="deleteMaterial({{ material.id }})" class="text-red-600 hover:text-red-800">
                            Delete
                        </button>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="text-center py-12">
            <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path>
            </svg>
            <h3 class="mt-2 text-sm font-medium text-gray-900">No materials yet</h3>
            <p class="mt-1 text-sm text-gray-500">Upload your first sales material to enhance research output.</p>
            <div class="mt-6">
                <button onclick="openUploadModal()" class="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700">
                    Upload Material
                </button>
            </div>
        </div>
        {% endif %}
    </div>
</div>

<!-- Upload Modal -->
<div id="uploadModal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
    <div class="bg-white rounded-lg p-6 max-w-md w-full mx-4">
        <h2 class="text-xl font-bold mb-4">Upload Material</h2>
        <form id="uploadForm" enctype="multipart/form-data">
            <div class="mb-4">
                <label class="block text-sm font-medium text-gray-700 mb-2">File</label>
                <input type="file" name="file" accept=".pdf,.docx,.pptx,.txt,.md" required
                       class="w-full border rounded-lg p-2">
                <p class="text-xs text-gray-500 mt-1">PDF, DOCX, PPTX, TXT, or MD (max 20MB)</p>
            </div>
            <div class="mb-6">
                <label class="block text-sm font-medium text-gray-700 mb-2">Material Type</label>
                <select name="material_type" class="w-full border rounded-lg p-2">
                    <option value="case_study">Case Study</option>
                    <option value="battle_card">Battle Card</option>
                    <option value="product_doc">Product Documentation</option>
                    <option value="sales_deck">Sales Deck</option>
                    <option value="other">Other</option>
                </select>
            </div>
            <div class="flex justify-end space-x-3">
                <button type="button" onclick="closeUploadModal()" class="px-4 py-2 text-gray-600 hover:text-gray-800">
                    Cancel
                </button>
                <button type="submit" class="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700">
                    Upload
                </button>
            </div>
        </form>
    </div>
</div>

<script>
function openUploadModal() {
    document.getElementById('uploadModal').classList.remove('hidden');
    document.getElementById('uploadModal').classList.add('flex');
}

function closeUploadModal() {
    document.getElementById('uploadModal').classList.add('hidden');
    document.getElementById('uploadModal').classList.remove('flex');
}

document.getElementById('uploadForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);

    const response = await fetch('/materials/upload', {
        method: 'POST',
        body: formData
    });

    const result = await response.json();
    if (result.success) {
        window.location.reload();
    } else {
        alert('Upload failed: ' + result.error);
    }
});

async function deleteMaterial(id) {
    if (!confirm('Delete this material?')) return;

    const response = await fetch(`/materials/${id}`, { method: 'DELETE' });
    const result = await response.json();

    if (result.success) {
        window.location.reload();
    } else {
        alert('Delete failed');
    }
}
</script>
{% endblock %}
```

---

## Phase 12: Navigation Update

### Step 12.1: Add materials link to base.html navigation

```html
<!-- In the nav section, add: -->
<a href="/materials" class="text-gray-600 hover:text-gray-900">Materials</a>
```

---

## Final Checklist

### Environment Variables to Add

```bash
# .env
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=auggie-materials
OPENAI_API_KEY=your_openai_key
```

### Dependencies to Add (requirements.txt)

```
boto3>=1.34.0
pypdf>=4.0.0
python-docx>=1.1.0
python-pptx>=0.6.23
openai>=1.0.0
```

### SQL to Run on Railway

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## Implementation Order Summary

| Phase | Description | Est. Hours |
|-------|-------------|------------|
| 1 | Database setup (pgvector, tables) | 3 |
| 2 | Cloudflare R2 setup + storage service | 5 |
| 3 | Document parser | 8 |
| 4 | Chunking service | 5 |
| 5 | Embeddings service | 3 |
| 6 | Database operations | 5 |
| 7 | Retrieval service | 5 |
| 8 | Materials processing pipeline | 8 |
| 9 | Claude integration | 3 |
| 10 | API routes | 5 |
| 11 | UI template | 8 |
| 12 | Testing & polish | 10 |

**Total: ~68-75 hours**
