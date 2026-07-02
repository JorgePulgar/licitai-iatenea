import os
import pytest
from unittest.mock import MagicMock, mock_open, patch

from app.services.ingestion import download_pliego_bytes, delete_pliego_blob
from app.core.config import settings


class TestDownloadPliegoBytes:
    def test_local_file(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"PDF content")
        result = download_pliego_bytes(f"file://{pdf}")
        assert result == b"PDF content"

    def test_local_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            download_pliego_bytes("file:///nonexistent/path/test.pdf")

    def test_azure_no_credentials_raises(self, mocker):
        mocker.patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", None)
        with pytest.raises(ValueError, match="No Azure Storage credentials"):
            download_pliego_bytes("https://account.blob.core.windows.net/pliegos-raw/abc/file.pdf")

    def test_azure_malformed_url_raises(self, mocker):
        mocker.patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", "AccountName=test;")
        mocker.patch("app.services.ingestion.BlobServiceClient")
        with pytest.raises(ValueError, match="Malformed blob URL"):
            download_pliego_bytes("https://account.blob.core.windows.net/wrong-container/abc/file.pdf")

    def test_azure_success(self, mocker):
        mocker.patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", "AccountName=test;")
        mocker.patch.object(settings, "AZURE_STORAGE_CONTAINER_NAME", "pliegos-raw")

        mock_blob_service = mocker.patch("app.services.ingestion.BlobServiceClient")
        mock_blob_client = MagicMock()
        mock_blob_client.download_blob.return_value.readall.return_value = b"PDF data"
        mock_blob_service.from_connection_string.return_value.get_blob_client.return_value = mock_blob_client

        result = download_pliego_bytes(
            "https://account.blob.core.windows.net/pliegos-raw/uuid/file.pdf"
        )
        assert result == b"PDF data"


class TestDeletePliegoBlob:
    def test_local_file_deleted(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"content")
        delete_pliego_blob(f"file://{pdf}")
        assert not pdf.exists()

    def test_local_file_missing_does_not_raise(self):
        delete_pliego_blob("file:///nonexistent/test.pdf")

    def test_azure_no_credentials_is_noop(self, mocker):
        mocker.patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", None)
        # Should not raise
        delete_pliego_blob("https://account.blob.core.windows.net/pliegos-raw/uuid/file.pdf")

    def test_azure_calls_delete_blob(self, mocker):
        mocker.patch.object(settings, "AZURE_STORAGE_CONNECTION_STRING", "AccountName=test;")
        mocker.patch.object(settings, "AZURE_STORAGE_CONTAINER_NAME", "pliegos-raw")

        mock_blob_service = mocker.patch("app.services.ingestion.BlobServiceClient")
        mock_blob_client = MagicMock()
        mock_blob_service.from_connection_string.return_value.get_blob_client.return_value = mock_blob_client

        delete_pliego_blob("https://account.blob.core.windows.net/pliegos-raw/uuid/file.pdf")
        mock_blob_client.delete_blob.assert_called_once()
