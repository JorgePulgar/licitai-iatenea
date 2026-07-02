"""
Backfill `pliegos.doc_title` for documents ingested before the column existed.

Only re-runs OCR (one Azure DI call per pliego) to extract the page-1 title and
UPDATEs the column. Does NOT touch chunks, embeddings, or the AI Search index —
unlike scripts/reindex_licitacion.py, which rebuilds everything.

Idempotent: skips pliegos that already have a doc_title. Safe to re-run.

Run from backend/ directory:
    python scripts/backfill_doc_titles.py            # all pliegos missing a title
    python scripts/backfill_doc_titles.py <licitacion_id>   # only that licitacion
"""

import sys
import os
import asyncio

# Windows consoles default to cp1252; títulos y símbolos llevan acentos/✓ → forzar UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import get_logger
from app.db.database import SessionLocal
from app.models.domain import Pliego
from app.services.ocr import extract_doc_title_from_blob

logger = get_logger(__name__)


async def backfill(licitacion_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        query = db.query(Pliego).filter(Pliego.doc_title.is_(None))
        if licitacion_id:
            query = query.filter(Pliego.licitacion_id == licitacion_id)
        pliegos = query.all()

        if not pliegos:
            print("No pliegos pending a title backfill.")
            return

        print(f"Found {len(pliegos)} pliego(s) without doc_title.")
        filled = 0
        for pliego in pliegos:
            try:
                title = await extract_doc_title_from_blob(pliego.blob_url)
            except Exception as e:
                logger.error(f"OCR failed for pliego {pliego.id}: {e}")
                print(f"  ✗ {pliego.id} ({pliego.filename}) — error: {e}")
                continue

            if title:
                pliego.doc_title = title
                db.commit()
                filled += 1
                print(f"  ✓ {pliego.id} ({pliego.filename}) → {title!r}")
            else:
                print(f"  – {pliego.id} ({pliego.filename}) — no title found, left NULL")

        print(f"Done. {filled}/{len(pliegos)} titles filled.")
    finally:
        db.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(backfill(target))
