"""
Re-index all pliegos for a given licitacion_id.

Use when a licitacion shows as 'indexed' in DB but has 0 chunks in Azure AI Search
(silent indexing failure during initial pipeline run).

Run from backend/ directory:
    python scripts/reindex_licitacion.py <licitacion_id>
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.domain import Pliego
from app.services.indexing import delete_pliego_from_index
from app.services.pipeline import run_ocr_and_index_pipeline


async def reindex(licitacion_id: str) -> None:
    db = SessionLocal()
    try:
        pliegos = db.query(Pliego).filter(Pliego.licitacion_id == licitacion_id).all()
        if not pliegos:
            print(f"No pliegos found for licitacion {licitacion_id}")
            return

        print(f"Found {len(pliegos)} pliegos for licitacion {licitacion_id}")
        for pliego in pliegos:
            print(f"  Deleting old chunks for pliego {pliego.id} ...")
            delete_pliego_from_index(pliego.id)
            print(f"  Re-indexing pliego {pliego.id} ({pliego.filename}) ...")
            result = await run_ocr_and_index_pipeline(pliego.id, db=db)
            print(f"  → status={result.status}, chunks_indexed={result.chunks_indexed}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/reindex_licitacion.py <licitacion_id>")
        sys.exit(1)

    licitacion_id = sys.argv[1]
    asyncio.run(reindex(licitacion_id))
