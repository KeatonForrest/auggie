"""storage.py - Cloudflare R2 file storage operations."""

import boto3
from botocore.config import Config
from uuid import uuid4
from typing import BinaryIO, Optional

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
        """Upload a file and return the storage key.

        Args:
            file: File-like object to upload
            user_id: User ID for namespacing
            filename: Original filename

        Returns:
            Storage key for the uploaded file
        """
        # Generate unique key: materials/{user_id}/{uuid}_{filename}
        file_id = str(uuid4())[:8]
        # Sanitize filename
        safe_filename = "".join(c for c in filename if c.isalnum() or c in '._-')
        key = f"materials/{user_id}/{file_id}_{safe_filename}"

        self.client.upload_fileobj(file, self.bucket, key)
        return key

    def download_file(self, key: str) -> bytes:
        """Download a file by its storage key.

        Args:
            key: Storage key from upload_file

        Returns:
            File contents as bytes
        """
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response['Body'].read()

    def delete_file(self, key: str) -> None:
        """Delete a file by its storage key.

        Args:
            key: Storage key to delete
        """
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a temporary download URL.

        Args:
            key: Storage key
            expires_in: URL expiration time in seconds (default 1 hour)

        Returns:
            Presigned URL for downloading the file
        """
        return self.client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': key},
            ExpiresIn=expires_in
        )

    def file_exists(self, key: str) -> bool:
        """Check if a file exists.

        Args:
            key: Storage key to check

        Returns:
            True if file exists, False otherwise
        """
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False
