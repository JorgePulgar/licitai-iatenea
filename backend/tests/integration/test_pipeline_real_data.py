import pytest
import os
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models.domain import Licitacion, Pliego, PliegoStatus
from app.services.pipeline import run_ocr_and_index_pipeline
from datetime import datetime, timezone

# Test DB setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_real_pipeline.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Path relative to backend/
FIXTURES_DIR = "tests/fixtures/pliegos"

@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def get_real_pliegos():
    """Lists real PDF files in the fixtures folder."""
    if not os.path.exists(FIXTURES_DIR):
        return []
    return [f for f in os.listdir(FIXTURES_DIR) if f.endswith(".pdf")]

@pytest.mark.parametrize("filename", get_real_pliegos())
@patch("app.services.pipeline.index_chunks")
@patch("app.services.embeddings.embed_chunks")
@patch("app.services.ocr.download_pliego_bytes")
@patch("app.services.ocr.DocumentIntelligenceClient")
@patch("app.services.ocr.settings")
@pytest.mark.asyncio
async def test_pipeline_with_real_files(
    mock_settings, 
    mock_di_client, 
    mock_download, 
    mock_embed, 
    mock_index, 
    filename, 
    db
):
    # 1. Load real file content
    file_path = os.path.join(FIXTURES_DIR, filename)
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    
    mock_download.return_value = file_bytes
    
    # 2. Azure Mocks
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = "http://mock"
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "mock-key"
    
    # Mock OCR result
    mock_result = MagicMock()
    mock_paragraph = MagicMock()
    mock_paragraph.content = f"Real extraction content from {filename}"
    mock_paragraph.bounding_regions = [MagicMock(page_number=1, polygon=[0,0,1,1])]
    mock_result.paragraphs = [mock_paragraph]
    mock_result.pages = [MagicMock(words=[MagicMock(confidence=0.9)])]
    
    mock_poller = MagicMock()
    mock_poller.result.return_value = mock_result
    mock_di_client.return_value.begin_analyze_document.return_value = mock_poller
    
    # Mock downstream services
    from app.models.schemas import IndexResult
    mock_embed.side_effect = lambda x: x
    mock_index.return_value = IndexResult(pliego_id=filename, chunks_indexed=1, pages_count=1, status="success")

    # 3. Create DB entry (Licitacion + child Pliego — post-S2 model)
    pliego_id = f"test-id-{filename[:10]}"
    licitacion_id = f"lic-{filename[:10]}"
    db.add(Licitacion(
        id=licitacion_id,
        user_id="user_test",
        title=filename,
        status="processing",
    ))
    db.add(Pliego(
        id=pliego_id,
        licitacion_id=licitacion_id,
        document_type="pcap",
        filename=filename,
        blob_url=f"local://{filename}",
        blob_path=filename,
        size_bytes=len(file_bytes),
        status=PliegoStatus.uploaded,
        uploaded_at=datetime.now(timezone.utc)
    ))
    db.commit()

    # 4. Run Pipeline
    result = await run_ocr_and_index_pipeline(pliego_id, db=db)
    
    # 5. Assertions
    assert result.status == "success"
    
    pliego = db.query(Pliego).filter(Pliego.id == pliego_id).first()
    assert pliego.status == PliegoStatus.indexed
    assert pliego.processed_at is not None
