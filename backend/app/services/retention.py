"""
LIC-063 — Scheduled deletion of expired pliegos.

Meant to run daily (e.g., via cron or Azure Functions timer trigger).
For each pliego whose retention_until has passed, deletes:
  1. Azure Blob Storage file
  2. Chunks from Azure AI Search index
  3. DB records (Pliego and parent Licitacion if orphaned)
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger, set_log_context
from app.db.database import SessionLocal
from app.models.domain import Licitacion, Pliego
from app.services.indexing import delete_pliego_from_index
from app.services.ingestion import delete_pliego_blob

logger = get_logger(__name__)


def delete_expired_pliegos(db: Session | None = None) -> dict[str, int]:
    """
    Deletes all pliegos whose retention_until is in the past.
    Returns a summary dict: {"deleted": N, "errors": M}.
    """
    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True

    deleted = 0
    errors = 0

    try:
        now = datetime.now(timezone.utc)
        expired = (
            db.query(Pliego)
            .filter(Pliego.retention_until <= now)
            .all()
        )

        logger.info(f"Retention job: found {len(expired)} expired pliegos.")

        for pliego in expired:
            set_log_context(pliego_id=pliego.id)
            try:
                delete_pliego_from_index(pliego.id)
                delete_pliego_blob(pliego.blob_url)

                licitacion_id = pliego.licitacion_id
                db.delete(pliego)
                db.flush()

                # If parent licitacion has no remaining documents, delete it too
                remaining = (
                    db.query(Pliego)
                    .filter(Pliego.licitacion_id == licitacion_id)
                    .count()
                )
                if remaining == 0:
                    licitacion = db.query(Licitacion).filter(
                        Licitacion.id == licitacion_id
                    ).first()
                    if licitacion:
                        db.delete(licitacion)

                db.commit()
                deleted += 1
                logger.info(f"Pliego {pliego.id} deleted (retention expired).")

            except Exception as e:
                db.rollback()
                errors += 1
                logger.error(f"Error deleting expired pliego {pliego.id}: {e}")

    finally:
        if own_session:
            db.close()

    logger.info(f"Retention job complete: deleted={deleted}, errors={errors}.")
    return {"deleted": deleted, "errors": errors}
