"""
Diagnostic: run Azure Document Intelligence on a stored pliego and print raw counts.

Confirms whether DI analyzes the whole PDF or stops after a few pages
(F0 free-tier limit, page param, etc.). Read-only — does not touch the index.

Run from backend/ directory:
    python scripts/diag_di.py <licitacion_id>
"""

import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pypdf import PdfReader
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.domain import Pliego
from app.services.ingestion import download_pliego_bytes


def diag(licitacion_id: str) -> None:
    db = SessionLocal()
    try:
        pliegos = db.query(Pliego).filter(Pliego.licitacion_id == licitacion_id).all()
        if not pliegos:
            print(f"No pliegos found for licitacion {licitacion_id}")
            return

        client = DocumentIntelligenceClient(
            endpoint=settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
            credential=AzureKeyCredential(settings.AZURE_DOCUMENT_INTELLIGENCE_KEY),
        )

        for pliego in pliegos:
            print("=" * 70)
            print(f"Pliego {pliego.id} ({pliego.document_type}) {pliego.filename}")
            pdf_bytes = download_pliego_bytes(pliego.blob_url)

            # Ground truth: real page count from the PDF itself.
            reader = PdfReader(io.BytesIO(pdf_bytes))
            print(f"  pypdf page count        : {len(reader.pages)}")
            print(f"  pdf size bytes          : {len(pdf_bytes)}")

            poller = client.begin_analyze_document(
                "prebuilt-layout",
                body=io.BytesIO(pdf_bytes),
                content_type="application/pdf",
            )
            result = poller.result()

            print(f"  DI result.pages         : {len(result.pages or [])}")
            print(f"  DI result.paragraphs    : {len(result.paragraphs or [])}")
            print(f"  DI result.tables        : {len(result.tables or [])}")

            # Which page numbers DI actually saw.
            para_pages = set()
            for p in (result.paragraphs or []):
                if p.bounding_regions:
                    para_pages.add(p.bounding_regions[0].page_number)
            print(f"  paragraph page numbers  : {sorted(para_pages)}")

            if result.pages:
                first = result.pages[0]
                last = result.pages[-1]
                print(f"  first DI page.page_number: {getattr(first, 'page_number', '?')}")
                print(f"  last  DI page.page_number: {getattr(last, 'page_number', '?')}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/diag_di.py <licitacion_id>")
        sys.exit(1)
    diag(sys.argv[1])
