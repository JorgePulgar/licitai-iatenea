"""
LIC-070 — E2E integration tests for the full pipeline.

Covers:
  - Happy path: pipeline processes pliego, status → indexed, quality score set
  - OCR quality detection: ocr_quality_score and low_quality_flag persisted
  - Degradation: DI failure → pliego status = error, error_message set
  - Citation validation (LIC-057): citations beyond page_count are filtered
  - Unanswerable detector (LIC-058): LLM no-info response → standard message
  - Delete: licitacion + blobs + index removed cleanly

Tests run with mocked Azure services — no real credentials required.
"""
import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.domain import Licitacion, Pliego, PliegoStatus, User
from app.models.schemas import Citation, IndexResult, QueryResponse

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_e2e.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def licitacion_with_pliego(db):
    """Seeds one Licitacion + one Pliego in processing state."""
    lic = Licitacion(
        id="lic-e2e",
        user_id="user-e2e",
        title="E2E Test Licitacion",
        status="processing",
        created_at=_NOW,
        updated_at=_NOW,
    )
    pliego = Pliego(
        id="pliego-e2e",
        licitacion_id="lic-e2e",
        document_type="pcap",
        filename="test.pdf",
        blob_url="file://test.pdf",
        blob_path="test.pdf",
        size_bytes=1024,
        status=PliegoStatus.uploaded,
        uploaded_at=_NOW,
        retention_until=_NOW,
    )
    db.add_all([lic, pliego])
    db.commit()
    return lic, pliego


def _make_di_result(avg_confidence: float = 0.92, num_pages: int = 5):
    """Builds a mock Azure Document Intelligence AnalyzeResult."""
    result = MagicMock()
    word = MagicMock(confidence=avg_confidence)
    page = MagicMock(words=[word])
    result.pages = [page] * num_pages

    para = MagicMock()
    para.content = "Fragmento de prueba del pliego de cláusulas administrativas."
    region = MagicMock(page_number=1, polygon=[0, 0, 1, 0, 1, 1, 0, 1])
    para.bounding_regions = [region]
    result.paragraphs = [para]
    return result


# ── Pipeline happy path ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("app.services.pipeline.index_chunks")
@patch("app.services.embeddings.embed_chunks")
@patch("app.services.ocr.validate_pdf_bytes")
@patch("app.services.ocr.download_pliego_bytes")
@patch("app.services.ocr._call_document_intelligence")
@patch("app.services.ocr.settings")
async def test_pipeline_happy_path(
    mock_settings, mock_di_call, mock_download, mock_validate, mock_embed, mock_index,
    db, licitacion_with_pliego,
):
    _, pliego = licitacion_with_pliego

    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = "https://mock"
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "mock-key"
    mock_download.return_value = b"%PDF-1.4 fake content"
    mock_validate.return_value = None
    mock_di_call.return_value = _make_di_result(avg_confidence=0.92, num_pages=3)
    mock_embed.side_effect = lambda chunks: chunks
    mock_index.return_value = IndexResult(
        pliego_id="pliego-e2e", chunks_indexed=1, pages_count=3, status="success"
    )

    from app.services.pipeline import run_ocr_and_index_pipeline
    result = await run_ocr_and_index_pipeline("pliego-e2e", db=db)

    assert result.status == "success"
    db.refresh(pliego)
    assert pliego.status == PliegoStatus.indexed
    assert pliego.processed_at is not None
    assert pliego.ocr_quality_score is not None
    assert pliego.ocr_quality_score == pytest.approx(0.92, abs=0.01)
    assert pliego.low_quality_flag is False
    assert pliego.page_count == 3


# ── OCR quality detection (LIC-059) ──────────────────────────────────────────

@pytest.mark.asyncio
@patch("app.services.pipeline.index_chunks")
@patch("app.services.embeddings.embed_chunks")
@patch("app.services.ocr.validate_pdf_bytes")
@patch("app.services.ocr.download_pliego_bytes")
@patch("app.services.ocr._call_document_intelligence")
@patch("app.services.ocr.settings")
async def test_pipeline_sets_low_quality_flag_when_confidence_below_threshold(
    mock_settings, mock_di_call, mock_download, mock_validate, mock_embed, mock_index,
    db, licitacion_with_pliego,
):
    _, pliego = licitacion_with_pliego

    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = "https://mock"
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "mock-key"
    mock_download.return_value = b"%PDF-1.4 fake"
    mock_validate.return_value = None
    mock_di_call.return_value = _make_di_result(avg_confidence=0.65)
    mock_embed.side_effect = lambda chunks: chunks
    mock_index.return_value = IndexResult(
        pliego_id="pliego-e2e", chunks_indexed=1, pages_count=1, status="success"
    )

    from app.services.pipeline import run_ocr_and_index_pipeline
    await run_ocr_and_index_pipeline("pliego-e2e", db=db)

    db.refresh(pliego)
    assert pliego.ocr_quality_score == pytest.approx(0.65, abs=0.01)
    assert pliego.low_quality_flag is True


# ── Degradation: DI failure (LIC-061a) ───────────────────────────────────────

@pytest.mark.asyncio
@patch("app.services.ocr.validate_pdf_bytes")
@patch("app.services.ocr.download_pliego_bytes")
@patch("app.services.ocr._call_document_intelligence")
@patch("app.services.ocr.settings")
async def test_pipeline_sets_error_status_when_di_fails(
    mock_settings, mock_di_call, mock_download, mock_validate,
    db, licitacion_with_pliego,
):
    _, pliego = licitacion_with_pliego

    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = "https://mock"
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "mock-key"
    mock_download.return_value = b"%PDF-1.4 fake"
    mock_validate.return_value = None
    mock_di_call.side_effect = RuntimeError("Simulated DI transient failure")

    from app.services.pipeline import run_ocr_and_index_pipeline
    result = await run_ocr_and_index_pipeline("pliego-e2e", db=db)

    assert result.status == "error"
    db.refresh(pliego)
    assert pliego.status == PliegoStatus.error
    assert pliego.error_message is not None
    assert "OCR error" in pliego.error_message or "Simulated" in pliego.error_message


# ── Citation validation (LIC-057) ────────────────────────────────────────────

def test_citations_beyond_page_count_are_filtered():
    from app.services.query import validate_citations

    citations = [
        Citation(content="text", page_number=3, pliego_id="p1", licitacion_id="l1",
                 filename="f.pdf", document_type="pcap"),
        Citation(content="text", page_number=99, pliego_id="p1", licitacion_id="l1",
                 filename="f.pdf", document_type="pcap"),
        Citation(content="text", page_number=None, pliego_id="p1", licitacion_id="l1",
                 filename="f.pdf", document_type="pcap"),
    ]
    page_counts = {"p1": 10}
    result = validate_citations(citations, page_counts)

    assert len(result) == 2
    assert all(c.page_number != 99 for c in result)


def test_citations_for_unknown_pliego_are_kept():
    from app.services.query import validate_citations

    citations = [
        Citation(content="text", page_number=100, pliego_id="unknown-id",
                 licitacion_id="l1", filename="f.pdf", document_type="pcap"),
    ]
    result = validate_citations(citations, page_counts={})
    assert len(result) == 1


# ── Unanswerable detector (LIC-058) ──────────────────────────────────────────

def test_is_unanswerable_detects_no_info_marker():
    from app.services.query import _is_unanswerable
    assert _is_unanswerable("No se encuentra en el pliego esta información.") is True
    assert _is_unanswerable("No he encontrado información sobre esto en el pliego.") is True
    assert _is_unanswerable("El presupuesto base es 100.000 €. [p. 3]") is False


@pytest.mark.asyncio
async def test_generate_answer_returns_standard_message_when_no_chunks():
    from app.services.query import generate_answer, _NO_INFO_ANSWER
    response = await generate_answer("¿Cuál es el plazo?", [], "lic-1", "Test")
    assert response.answer == _NO_INFO_ANSWER
    assert response.citations == []


# ── PDF validation (LIC-062) ─────────────────────────────────────────────────

def test_validate_pdf_bytes_rejects_encrypted_pdf():
    from unittest.mock import MagicMock, patch
    from app.services.ingestion import validate_pdf_bytes

    mock_reader = MagicMock()
    mock_reader.is_encrypted = True

    with patch("app.services.ingestion.PdfReader", return_value=mock_reader):
        with pytest.raises(ValueError, match="contraseña"):
            validate_pdf_bytes(b"fake", "doc.pdf")


def test_validate_pdf_bytes_rejects_corrupt_pdf():
    from app.services.ingestion import validate_pdf_bytes

    with pytest.raises(ValueError, match="válido|corrupto"):
        validate_pdf_bytes(b"not a pdf", "doc.pdf")


# ── Delete: licitacion cleanup ────────────────────────────────────────────────

@patch("app.services.indexing.delete_pliego_from_index")
@patch("app.services.ingestion.delete_pliego_blob")
def test_delete_licitacion_removes_all_data(
    mock_delete_blob, mock_delete_index, db, licitacion_with_pliego,
):
    from app.db.database import get_db
    from app.core.deps import get_current_user
    from app.models.domain import User
    from app.main import app
    from fastapi.testclient import TestClient

    lic, pliego = licitacion_with_pliego
    user = User(id="user-e2e", email="e2e@test.com", password_hash="x", is_active=True)
    db.add(user)
    db.commit()

    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        client = TestClient(app)
        response = client.delete(f"/api/v1/licitaciones/{lic.id}")
        assert response.status_code == 204

        assert db.query(Licitacion).filter(Licitacion.id == lic.id).first() is None
        assert db.query(Pliego).filter(Pliego.id == pliego.id).first() is None
        mock_delete_index.assert_called_once_with(pliego.id)
        mock_delete_blob.assert_called_once_with(pliego.blob_url)
    finally:
        app.dependency_overrides.clear()
