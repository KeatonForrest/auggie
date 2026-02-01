import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from io import BytesIO
from services.materials import MaterialsService


@pytest.fixture
def mock_r2_storage():
    with patch('services.materials.R2Storage') as mock:
        instance = MagicMock()
        instance.upload_file = MagicMock(return_value='s3://bucket/key')
        instance.delete_file = MagicMock(return_value=True)
        instance.download_file = MagicMock(return_value=b'file content')
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_document_parser():
    with patch('services.materials.DocumentParser') as mock:
        instance = MagicMock()
        instance.parse = MagicMock(return_value='parsed text content')
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_chunking_service():
    with patch('services.materials.ChunkingService') as mock:
        instance = MagicMock()
        chunk1 = MagicMock(content='chunk1 text', section_title='Section 1')
        chunk2 = MagicMock(content='chunk2 text', section_title='Section 2')
        chunk3 = MagicMock(content='chunk3 text', section_title='Section 3')
        instance.chunk_document = MagicMock(return_value=[chunk1, chunk2, chunk3])
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_embedding_service():
    with patch('services.materials.EmbeddingService') as mock:
        instance = MagicMock()
        instance.embed_batch = AsyncMock(return_value=[
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
            [0.7, 0.8, 0.9]
        ])
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_database():
    with patch('services.materials.database') as mock:
        mock.create_material = AsyncMock(return_value={
            'id': 'mat_123',
            'user_id': 'user_456',
            'filename': 'test.pdf',
            'file_type': 'pdf',
            'material_type': 'other',
            'storage_key': 's3://bucket/key',
            'status': 'pending'
        })
        mock.update_material_status = AsyncMock()
        mock.save_chunks = AsyncMock(return_value=3)
        mock.delete_material = AsyncMock(return_value='s3://bucket/key')
        mock.get_material = AsyncMock(return_value={
            'id': 'mat_123',
            'user_id': 'user_456',
            'storage_key': 's3://bucket/key',
            'file_type': 'pdf',
            'material_type': 'case_study'
        })
        mock.delete_chunks_for_material = AsyncMock()
        yield mock


@pytest.fixture
def materials_service(mock_r2_storage, mock_document_parser, mock_chunking_service,
                      mock_embedding_service, mock_database):
    return MaterialsService()


class TestUploadMaterial:
    @pytest.mark.asyncio
    async def test_upload_material_success(self, materials_service, mock_r2_storage,
                                          mock_database):
        file = BytesIO(b'test pdf content')
        with patch('asyncio.create_task') as mock_task:
            result = await materials_service.upload_material(
                user_id='user_456', file=file, filename='test.pdf',
                material_type='case_study'
            )

        assert result['id'] == 'mat_123'
        assert result['status'] == 'pending'
        mock_database.create_material.assert_called_once()
        mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_material_unsupported_type(self, materials_service):
        with pytest.raises(ValueError, match='Unsupported file type'):
            await materials_service.upload_material(
                user_id='user_456', file=BytesIO(b'x'), filename='test.exe'
            )

    @pytest.mark.asyncio
    async def test_upload_material_file_too_large(self, materials_service):
        file = BytesIO(b'x' * (21 * 1024 * 1024))
        with pytest.raises(ValueError, match='File too large'):
            await materials_service.upload_material(
                user_id='user_456', file=file, filename='test.pdf'
            )

    @pytest.mark.asyncio
    async def test_upload_material_empty_file(self, materials_service):
        with pytest.raises(ValueError, match='File is empty'):
            await materials_service.upload_material(
                user_id='user_456', file=BytesIO(b''), filename='test.pdf'
            )


class TestProcessMaterial:
    @pytest.mark.asyncio
    async def test_process_material_success(self, materials_service, mock_document_parser,
                                           mock_chunking_service, mock_embedding_service,
                                           mock_database):
        await materials_service.process_material(
            material_id='mat_123', user_id='user_456',
            file_bytes=b'pdf content', file_type='pdf', material_type='case_study'
        )

        mock_document_parser.parse.assert_called_once_with(b'pdf content', 'pdf')
        mock_chunking_service.chunk_document.assert_called_once_with('parsed text content', 'case_study')
        mock_embedding_service.embed_batch.assert_called_once_with(
            ['chunk1 text', 'chunk2 text', 'chunk3 text']
        )
        mock_database.save_chunks.assert_called_once()
        # Status updates: 'processing' then 'ready'
        assert mock_database.update_material_status.call_count == 2
        mock_database.update_material_status.assert_any_call('mat_123', 'processing')
        mock_database.update_material_status.assert_any_call('mat_123', 'ready', chunk_count=3)

    @pytest.mark.asyncio
    async def test_process_material_empty_text(self, materials_service, mock_document_parser,
                                               mock_database):
        mock_document_parser.parse.return_value = ''

        await materials_service.process_material(
            material_id='mat_123', user_id='user_456',
            file_bytes=b'pdf content', file_type='pdf', material_type='other'
        )

        mock_database.update_material_status.assert_any_call(
            'mat_123', 'failed',
            error_message="Could not extract text from document"
        )

    @pytest.mark.asyncio
    async def test_process_material_no_chunks(self, materials_service, mock_document_parser,
                                              mock_chunking_service, mock_database):
        mock_chunking_service.chunk_document.return_value = []

        await materials_service.process_material(
            material_id='mat_123', user_id='user_456',
            file_bytes=b'pdf content', file_type='pdf', material_type='other'
        )

        mock_database.update_material_status.assert_any_call(
            'mat_123', 'failed',
            error_message="Document too short to process"
        )


class TestProcessMaterialSafe:
    @pytest.mark.asyncio
    async def test_catches_exception(self, materials_service, mock_document_parser,
                                     mock_database):
        mock_document_parser.parse.side_effect = Exception('Parsing failed')

        await materials_service._process_material_safe(
            material_id='mat_123', user_id='user_456',
            file_bytes=b'pdf content', file_type='pdf', material_type='other'
        )

        mock_database.update_material_status.assert_called_with(
            'mat_123', 'failed',
            error_message='Parsing failed'
        )


class TestDeleteMaterial:
    @pytest.mark.asyncio
    async def test_delete_found(self, materials_service, mock_r2_storage, mock_database):
        result = await materials_service.delete_material('mat_123', 'user_456')
        assert result is True
        mock_database.delete_material.assert_called_once_with('mat_123', 'user_456')

    @pytest.mark.asyncio
    async def test_delete_not_found(self, materials_service, mock_database):
        mock_database.delete_material.return_value = None
        result = await materials_service.delete_material('mat_999', 'user_456')
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_r2_failure_still_returns_true(self, materials_service,
                                                        mock_r2_storage, mock_database):
        mock_r2_storage.delete_file.side_effect = Exception('R2 error')
        result = await materials_service.delete_material('mat_123', 'user_456')
        assert result is True


class TestReprocessMaterial:
    @pytest.mark.asyncio
    async def test_reprocess_found(self, materials_service, mock_database, mock_r2_storage):
        with patch('asyncio.create_task') as mock_task:
            result = await materials_service.reprocess_material('mat_123', 'user_456')
        assert result is True
        mock_database.get_material.assert_called_once_with('mat_123', 'user_456')
        mock_database.delete_chunks_for_material.assert_called_once_with('mat_123')
        mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_reprocess_not_found(self, materials_service, mock_database):
        mock_database.get_material.return_value = None
        result = await materials_service.reprocess_material('mat_999', 'user_456')
        assert result is False
