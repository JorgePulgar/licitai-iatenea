import uuid
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.domain import Licitacion, Pliego
from app.models.schemas import LicitacionCreateRequest
from app.services.pipeline import run_ocr_and_index_pipeline

logger = get_logger(__name__)


def create_licitacion(
    request: LicitacionCreateRequest,
    user_id: str,
    db: Session,
    background_tasks: BackgroundTasks,
) -> Licitacion:
    """
    Creates a Licitacion record and one Pliego per uploaded document,
    then enqueues OCR+indexing as background tasks for each document.
    """
    licitacion_id = str(uuid.uuid4())
    licitacion = Licitacion(
        id=licitacion_id,
        user_id=user_id,
        title=request.title,
        status="processing",
        estado="elaborando",  # estado comercial inicial al subir la licitación
        deadline=request.deadline,
    )
    db.add(licitacion)

    # Build (doc_info, document_type) pairs — pcap is always present
    documents_to_create = [(request.pcap, "pcap")]
    if request.ppt:
        documents_to_create.append((request.ppt, "ppt"))
    for anexo in request.anexos:
        documents_to_create.append((anexo, "anexo"))

    now = datetime.now(timezone.utc)
    retention_until = now + timedelta(days=settings.RETENTION_DAYS)

    pliego_ids: list[str] = []
    for doc_info, doc_type in documents_to_create:
        pliego_id = str(uuid.uuid4())
        # Derive blob_path from blob_url (strip the storage host prefix)
        blob_path = doc_info.blob_url
        if "blob.core.windows.net/" in blob_path:
            blob_path = blob_path.split("blob.core.windows.net/", 1)[1]
        pliego = Pliego(
            id=pliego_id,
            licitacion_id=licitacion_id,
            document_type=doc_type.upper(),
            filename=doc_info.filename,
            blob_url=doc_info.blob_url,
            blob_path=blob_path,
            size_bytes=doc_info.size_bytes,
            uploaded_at=now,
            retention_until=retention_until,
        )
        db.add(pliego)
        pliego_ids.append(pliego_id)

    db.commit()
    db.refresh(licitacion)

    for pid in pliego_ids:
        background_tasks.add_task(run_ocr_and_index_pipeline, pid)

    logger.info(
        f"Licitacion {licitacion_id} created with {len(pliego_ids)} documents. "
        f"Pipeline enqueued for each."
    )
    return licitacion
