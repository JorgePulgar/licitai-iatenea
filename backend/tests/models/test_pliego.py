import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models.domain import Pliego, PliegoStatus

# Usamos SQLite en memoria para tests de modelos
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_create_pliego(db):
    pliego = Pliego(
        id="test-uuid",
        licitacion_id="lic-123",
        document_type="pcap",
        filename="test.pdf",
        blob_url="https://storage.com/test.pdf",
        blob_path="test.pdf",
        size_bytes=1024,
    )
    db.add(pliego)
    db.commit()
    db.refresh(pliego)

    assert pliego.id == "test-uuid"
    assert pliego.filename == "test.pdf"
    assert pliego.status == PliegoStatus.uploaded
    assert isinstance(pliego.uploaded_at, datetime)
    assert pliego.processed_at is None

def test_pliego_status_enum(db):
    pliego = Pliego(
        id="test-2",
        licitacion_id="lic-123",
        document_type="pcap",
        filename="test2.pdf",
        blob_url="https://storage.com/test2.pdf",
        blob_path="test2.pdf",
        size_bytes=2048,
        status=PliegoStatus.processing,
    )
    db.add(pliego)
    db.commit()
    db.refresh(pliego)

    # status persists as a plain string (column is String, PliegoStatus is a str enum)
    assert pliego.status == PliegoStatus.processing
    assert pliego.status == "processing"
