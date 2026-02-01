"""Tests for services/storage.py - R2Storage class."""

import pytest
from unittest.mock import Mock, MagicMock, patch, ANY
from io import BytesIO
from botocore.config import Config

from services.storage import R2Storage


class TestR2StorageInit:
    """Tests for R2Storage.__init__."""

    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_init_calls_boto3_with_correct_settings(self, mock_boto3, mock_get_settings):
        """Test that __init__ calls boto3.client with correct settings."""
        # Setup mock settings
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test-account.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-access-key"
        mock_settings.r2_secret_access_key = "test-secret-key"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        # Create instance
        storage = R2Storage()

        # Verify boto3.client was called with correct parameters
        mock_boto3.client.assert_called_once_with(
            's3',
            endpoint_url="https://test-account.r2.cloudflarestorage.com",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
            config=ANY,  # Config object will be different instance
        )

        # Verify the config object has correct signature_version
        call_args = mock_boto3.client.call_args
        assert isinstance(call_args.kwargs['config'], Config)
        assert call_args.kwargs['config'].signature_version == 's3v4'

        # Verify bucket name is stored
        assert storage.bucket == "test-bucket"
        assert storage.client == mock_boto3.client.return_value


class TestR2StorageUploadFile:
    """Tests for R2Storage.upload_file."""

    @patch("services.storage.uuid4")
    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_upload_file_generates_key_and_uploads(self, mock_boto3, mock_get_settings, mock_uuid4):
        """Test upload_file generates correct key and calls upload_fileobj."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        # Mock uuid4 to return a known value
        mock_uuid = Mock()
        mock_uuid.__str__ = Mock(return_value="12345678-1234-1234-1234-123456789abc")
        mock_uuid4.return_value = mock_uuid

        # Create storage instance
        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Create test file
        test_file = BytesIO(b"test content")
        user_id = 42
        filename = "test_file.pdf"

        # Call upload_file
        result = storage.upload_file(test_file, user_id, filename)

        # Verify the key is correct
        expected_key = "materials/42/12345678_test_file.pdf"
        assert result == expected_key

        # Verify upload_fileobj was called with correct parameters
        mock_client.upload_fileobj.assert_called_once_with(
            test_file,
            "test-bucket",
            expected_key
        )

    @patch("services.storage.uuid4")
    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_upload_file_sanitizes_filename_removes_special_chars(
        self, mock_boto3, mock_get_settings, mock_uuid4
    ):
        """Test that special characters are removed from filename."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        # Mock uuid4
        mock_uuid = Mock()
        mock_uuid.__str__ = Mock(return_value="abcd1234")
        mock_uuid4.return_value = mock_uuid

        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Test file with special characters
        test_file = BytesIO(b"content")
        filename = "my file@name#with spaces$and%special&chars!.pdf"

        result = storage.upload_file(test_file, 1, filename)

        # Only alphanumeric, '.', '_', '-' should remain
        expected_key = "materials/1/abcd1234_myfilenamewithspacesandspecialchars.pdf"
        assert result == expected_key

    @patch("services.storage.uuid4")
    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_upload_file_keeps_allowed_chars(self, mock_boto3, mock_get_settings, mock_uuid4):
        """Test that allowed characters (alphanumeric, '.', '_', '-') are kept."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        # Mock uuid4
        mock_uuid = Mock()
        mock_uuid.__str__ = Mock(return_value="test1234")
        mock_uuid4.return_value = mock_uuid

        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Test file with only allowed characters
        test_file = BytesIO(b"content")
        filename = "My_Test-File.123.pdf"

        result = storage.upload_file(test_file, 99, filename)

        # All characters should be preserved
        expected_key = "materials/99/test1234_My_Test-File.123.pdf"
        assert result == expected_key


class TestR2StorageDownloadFile:
    """Tests for R2Storage.download_file."""

    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_download_file_calls_get_object_and_returns_bytes(
        self, mock_boto3, mock_get_settings
    ):
        """Test download_file calls get_object and returns Body.read()."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Mock the response from get_object
        mock_body = Mock()
        mock_body.read.return_value = b"file content data"
        mock_response = {'Body': mock_body}
        mock_client.get_object.return_value = mock_response

        # Call download_file
        key = "materials/1/test_file.pdf"
        result = storage.download_file(key)

        # Verify get_object was called with correct parameters
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key=key
        )

        # Verify the result is from Body.read()
        assert result == b"file content data"
        mock_body.read.assert_called_once()


class TestR2StorageDeleteFile:
    """Tests for R2Storage.delete_file."""

    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_delete_file_calls_delete_object(self, mock_boto3, mock_get_settings):
        """Test delete_file calls delete_object with correct parameters."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Call delete_file
        key = "materials/1/test_file.pdf"
        storage.delete_file(key)

        # Verify delete_object was called with correct parameters
        mock_client.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key=key
        )


class TestR2StorageGetPresignedUrl:
    """Tests for R2Storage.get_presigned_url."""

    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_get_presigned_url_with_default_expiration(
        self, mock_boto3, mock_get_settings
    ):
        """Test get_presigned_url with default expiration time."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Mock the presigned URL
        mock_client.generate_presigned_url.return_value = "https://presigned-url.com/file"

        # Call get_presigned_url with default expiration
        key = "materials/1/test_file.pdf"
        result = storage.get_presigned_url(key)

        # Verify generate_presigned_url was called with correct parameters
        mock_client.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': key},
            ExpiresIn=3600  # default
        )

        # Verify the result
        assert result == "https://presigned-url.com/file"

    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_get_presigned_url_with_custom_expiration(
        self, mock_boto3, mock_get_settings
    ):
        """Test get_presigned_url with custom expiration time."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Mock the presigned URL
        mock_client.generate_presigned_url.return_value = "https://presigned-url.com/file"

        # Call get_presigned_url with custom expiration
        key = "materials/1/test_file.pdf"
        custom_expires = 7200
        result = storage.get_presigned_url(key, expires_in=custom_expires)

        # Verify generate_presigned_url was called with custom expiration
        mock_client.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': key},
            ExpiresIn=7200
        )

        # Verify the result
        assert result == "https://presigned-url.com/file"


class TestR2StorageFileExists:
    """Tests for R2Storage.file_exists."""

    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_file_exists_returns_true_when_head_object_succeeds(
        self, mock_boto3, mock_get_settings
    ):
        """Test file_exists returns True when head_object succeeds."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Mock head_object to succeed (no exception)
        mock_client.head_object.return_value = {}

        # Call file_exists
        key = "materials/1/existing_file.pdf"
        result = storage.file_exists(key)

        # Verify head_object was called
        mock_client.head_object.assert_called_once_with(
            Bucket="test-bucket",
            Key=key
        )

        # Verify result is True
        assert result is True

    @patch("services.storage.get_settings")
    @patch("services.storage.boto3")
    def test_file_exists_returns_false_when_head_object_raises_exception(
        self, mock_boto3, mock_get_settings
    ):
        """Test file_exists returns False when head_object raises exception."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.r2_endpoint_url = "https://test.r2.cloudflarestorage.com"
        mock_settings.r2_access_key_id = "test-key"
        mock_settings.r2_secret_access_key = "test-secret"
        mock_settings.r2_bucket_name = "test-bucket"
        mock_get_settings.return_value = mock_settings

        storage = R2Storage()
        mock_client = mock_boto3.client.return_value
        storage.client = mock_client

        # Mock head_object to raise an exception (file not found)
        mock_client.head_object.side_effect = Exception("NoSuchKey")

        # Call file_exists
        key = "materials/1/nonexistent_file.pdf"
        result = storage.file_exists(key)

        # Verify head_object was called
        mock_client.head_object.assert_called_once_with(
            Bucket="test-bucket",
            Key=key
        )

        # Verify result is False
        assert result is False
