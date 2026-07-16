"""
Subida server-side de pliegos (DM7, spec-demo-minimal §3.3).

El flujo SAS de spec-1.1 no ha aterrizado y el flujo antiguo enviaba un SAS de
CONTENEDOR al navegador (finding de seguridad #1). El FE-minimal sube el PDF por
multipart y este módulo lo persiste desde el servidor: el navegador nunca ve
credenciales de Storage. Cuando llegue 1.1, este módulo se sustituye por SAS de
blob individual + validación server-side (deuda registrada).

Sin AZURE_STORAGE_CONNECTION_STRING (dev sin Azure) los ficheros se guardan en
disco local con URL ``file://`` — mismo esquema que ya entiende
``download_pliego_bytes`` para el pipeline.
"""

import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Directorio local para el modo dev sin Azure (relativo al working dir del backend).
LOCAL_UPLOADS_DIR = Path("uploads")


def store_pliego_pdf(content: bytes, filename: str) -> str:
    """Persiste el PDF y devuelve su ``blob_url`` (Azure o ``file://`` local).

    El nombre del blob se genera con UUID (el nombre original solo se conserva
    como sufijo saneado) para evitar colisiones y path traversal.
    """
    safe_name = Path(filename).name.replace(" ", "_") or "pliego.pdf"
    blob_name = f"{uuid.uuid4()}/{safe_name}"

    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        local_path = LOCAL_UPLOADS_DIR / blob_name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)
        url = f"file://{local_path.resolve().as_posix()}"
        logger.info(f"Pliego guardado en local (dev sin Azure): {url}")
        return url

    from azure.storage.blob import BlobServiceClient, ContentSettings

    service = BlobServiceClient.from_connection_string(
        settings.AZURE_STORAGE_CONNECTION_STRING
    )
    blob_client = service.get_blob_client(
        container=settings.AZURE_STORAGE_CONTAINER_NAME, blob=blob_name
    )
    blob_client.upload_blob(
        content,
        overwrite=False,
        content_settings=ContentSettings(content_type="application/pdf"),
    )
    logger.info(f"Pliego subido a Blob Storage: {blob_name} ({len(content)} bytes)")
    return blob_client.url
