"""
Re-OCR + re-index pliegos so they pick up section-aware chunking (Chunk.seq /
Chunk.section_heading and the matching AI Search fields).

Chunks indexed before that feature have no `seq`, so neighbor expansion ignores
them (they still retrieve, just without their contiguous chunks). This rebuilds
them fully. One Azure Document Intelligence call per pliego → it costs money and
runs against the shared dev resources; run it deliberately.

The script first syncs the index definition (create_or_update_index is additive,
so it just adds the new `seq`/`section_heading` fields) before re-uploading, or
the new fields would be dropped on upload.

Run from backend/ directory:
    python scripts/reindex_pliegos.py --all              # every pliego
    python scripts/reindex_pliegos.py <licitacion_id>    # only that licitacion
"""

import sys
import os
import asyncio

# Windows consoles default to cp1252; nombres y símbolos llevan acentos/✓ → forzar UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import get_logger
from app.db.database import SessionLocal
from app.models.domain import Pliego
from app.services.indexing import create_index_if_not_exists, delete_pliego_from_index
from app.services.pipeline import run_ocr_and_index_pipeline

logger = get_logger(__name__)


async def reindex(licitacion_id: str | None = None) -> None:
    # Sincroniza el índice (añade seq/section_heading) ANTES de subir nada.
    print("Syncing AI Search index definition (adds seq / section_heading) ...")
    create_index_if_not_exists()

    db = SessionLocal()
    try:
        query = db.query(Pliego)
        if licitacion_id:
            query = query.filter(Pliego.licitacion_id == licitacion_id)
        pliegos = query.all()

        if not pliegos:
            scope = f"licitacion {licitacion_id}" if licitacion_id else "the database"
            print(f"No pliegos found in {scope}.")
            return

        print(f"Found {len(pliegos)} pliego(s) to reindex.")
        ok = 0
        for pliego in pliegos:
            try:
                print(f"  Deleting old chunks for pliego {pliego.id} ...")
                delete_pliego_from_index(pliego.id)
                print(f"  Re-indexing {pliego.id} ({pliego.filename}) ...")
                result = await run_ocr_and_index_pipeline(pliego.id, db=db)
                print(f"    → status={result.status}, chunks_indexed={result.chunks_indexed}")
                if result.status in ("success", "partial_error"):
                    ok += 1
            except Exception as e:
                logger.error(f"Reindex failed for pliego {pliego.id}: {e}")
                print(f"    ✗ {pliego.id} ({pliego.filename}) — error: {e}")

        print(f"Done. {ok}/{len(pliegos)} pliego(s) reindexed.")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/reindex_pliegos.py --all | <licitacion_id>")
        sys.exit(1)

    arg = sys.argv[1]
    target = None if arg == "--all" else arg
    asyncio.run(reindex(target))
