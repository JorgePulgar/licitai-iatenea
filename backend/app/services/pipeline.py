from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.core.logging import get_logger, set_log_context
from app.db.database import SessionLocal
from app.models.domain import Licitacion, Pliego, PliegoStatus
from app.models.schemas import IndexResult
from app.services.indexing import index_chunks
from app.services.ocr import process_pliego

logger = get_logger(__name__)


def _update_licitacion_status(licitacion_id: str, db: Session) -> None:
    """Derives and persists licitacion status from the statuses of all its documents."""
    pliegos = db.query(Pliego).filter(Pliego.licitacion_id == licitacion_id).all()
    if not pliegos:
        return

    statuses = {p.status for p in pliegos}

    if PliegoStatus.processing in statuses or PliegoStatus.uploaded in statuses:
        new_status = "processing"
    elif statuses == {PliegoStatus.indexed}:
        new_status = "indexed"
    elif PliegoStatus.indexed in statuses and PliegoStatus.error in statuses:
        new_status = "partial_error"
    else:
        new_status = "error"

    licitacion = db.query(Licitacion).filter(Licitacion.id == licitacion_id).first()
    if licitacion:
        licitacion.status = new_status
        licitacion.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Licitacion {licitacion_id} status updated to '{new_status}'.")


async def run_ocr_and_index_pipeline(pliego_id: str, db: Session | None = None) -> IndexResult:
    """
    Orchestrates OCR → chunking → embedding → indexing for a single document.
    Updates both the Pliego and its parent Licitacion status when done.
    """
    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True

    set_log_context(pliego_id=pliego_id)

    try:
        pliego = db.query(Pliego).filter(Pliego.id == pliego_id).first()
        if not pliego:
            raise ValueError(f"Pliego {pliego_id} not found")

        pliego.status = PliegoStatus.processing
        db.commit()

        # Get user_id from parent licitacion (pliegos table has no user_id)
        licitacion = db.query(Licitacion).filter(Licitacion.id == pliego.licitacion_id).first()
        owner_user_id = licitacion.user_id if licitacion else ""

        # 1. OCR and chunking — pass full document context for index tagging
        chunks, quality_score, page_count, doc_title = await process_pliego(
            blob_url=pliego.blob_url,
            pliego_id=pliego_id,
            licitacion_id=pliego.licitacion_id,
            user_id=owner_user_id,
            document_type=pliego.document_type,
            filename=pliego.filename,
        )
        # page_count is the document's real page count (from OCR), not the number of
        # distinct chunk pages — citation validation (LIC-057) relies on it being the
        # true max valid page. Fall back to distinct chunk pages only if OCR gave none.
        if page_count is None:
            page_count = len(set(c.page_number for c in chunks if c.page_number)) or None

        # 2. Embeddings
        from app.services.embeddings import embed_chunks
        chunks = await embed_chunks(chunks)

        # 3. Indexing
        index_res = index_chunks(chunks)
        index_res.pages_count = page_count

        if index_res.status == "error":
            raise RuntimeError("Indexing failed")

        # 4. Finalize pliego — persist OCR quality score (threshold 0.8, see ocr.py)
        pliego.status = PliegoStatus.indexed
        pliego.processed_at = datetime.now(timezone.utc)
        pliego.chunk_count = index_res.chunks_indexed
        pliego.page_count = page_count
        pliego.doc_title = doc_title
        pliego.ocr_quality_score = quality_score
        pliego.low_quality_flag = quality_score is not None and quality_score < 0.8
        db.commit()

        # 5. Update parent licitacion status
        _update_licitacion_status(pliego.licitacion_id, db)

        return index_res

    except Exception as e:
        logger.error(f"Pipeline failed for pliego {pliego_id}: {e}")
        db.rollback()
        pliego = db.query(Pliego).filter(Pliego.id == pliego_id).first()
        if pliego:
            pliego.status = PliegoStatus.error
            pliego.error_message = str(e)
            db.commit()
            _update_licitacion_status(pliego.licitacion_id, db)
        return IndexResult(pliego_id=pliego_id, chunks_indexed=0, status="error")
    finally:
        if own_session:
            db.close()
