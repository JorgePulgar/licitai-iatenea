import io
import os
from azure.storage.blob import BlobServiceClient
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def validate_pdf_bytes(pdf_bytes: bytes, filename: str) -> None:
    """Raises ValueError with a user-facing message if PDF is encrypted or corrupt."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except (PdfReadError, PdfStreamError, Exception):
        raise ValueError(
            f"El archivo '{filename}' no es un PDF válido o está corrupto. "
            "Comprueba que el archivo no esté dañado e inténtalo de nuevo."
        )
    if reader.is_encrypted:
        raise ValueError(
            f"El archivo '{filename}' está protegido con contraseña. "
            "Elimina la contraseña del PDF antes de subirlo."
        )


def download_pliego_bytes(blob_url: str) -> bytes:
    """Downloads a pliego from Azure Blob Storage or local filesystem."""
    if blob_url.startswith("file://"):
        local_path = blob_url.replace("file://", "")
        with open(local_path, "rb") as f:
            return f.read()

    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise ValueError("No Azure Storage credentials configured.")

    blob_service_client = BlobServiceClient.from_connection_string(
        settings.AZURE_STORAGE_CONNECTION_STRING
    )

    from urllib.parse import unquote
    container_part = f"/{settings.AZURE_STORAGE_CONTAINER_NAME}/"
    if container_part not in blob_url:
        raise ValueError(f"Malformed blob URL or wrong container: {blob_url}")

    blob_name = unquote(blob_url.split(container_part)[-1])
    blob_client = blob_service_client.get_blob_client(
        container=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob=blob_name
    )
    return blob_client.download_blob().readall()


def delete_pliego_blob(blob_url: str) -> None:
    """Deletes a pliego blob from Azure Storage or local filesystem."""
    if blob_url.startswith("file://"):
        local_path = blob_url.replace("file://", "")
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                parent_dir = os.path.dirname(local_path)
                if not os.listdir(parent_dir):
                    os.rmdir(parent_dir)
            except Exception as e:
                logger.error(f"Error deleting local file {local_path}: {e}")
        return

    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        return

    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )
        container_part = f"/{settings.AZURE_STORAGE_CONTAINER_NAME}/"
        if container_part in blob_url:
            blob_name = blob_url.split(container_part)[-1]
            blob_client = blob_service_client.get_blob_client(
                container=settings.AZURE_STORAGE_CONTAINER_NAME,
                blob=blob_name
            )
            blob_client.delete_blob()
    except Exception as e:
        logger.error(f"Error deleting blob {blob_url}: {e}")
