"""Alta de licitación con subida server-side (DM7): el navegador no ve SAS."""
import io
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.domain import Pliego, User

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_upload.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def clean_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(tmp_path):
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    user = User(id="user-a", email="a@test.com", password_hash="x", is_active=True,
                created_at=_NOW, updated_at=_NOW)
    session.add(user)
    session.commit()

    app.dependency_overrides[get_db] = lambda: (yield session)
    app.dependency_overrides[get_current_user] = lambda: user
    # Subidas locales al tmp del test y pipeline OCR mockeado (offline).
    with patch("app.services.uploads.LOCAL_UPLOADS_DIR", tmp_path), \
         patch("app.services.licitacion.run_ocr_and_index_pipeline"):
        yield TestClient(app)

    session.close()
    Base.metadata.drop_all(bind=engine)


def test_upload_creates_licitacion_with_local_storage(client, tmp_path):
    pdf = _pdf_bytes()
    r = client.post(
        "/api/v1/licitaciones/upload",
        data={"title": "Licitación demo"},
        files={
            "pcap": ("pcap.pdf", pdf, "application/pdf"),
            "ppt": ("ppt.pdf", pdf, "application/pdf"),
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Licitación demo"
    assert body["status"] == "processing"
    types = sorted(d["document_type"] for d in body["documents"])
    assert types == ["PCAP", "PPT"]
    # Sin Azure configurado, los PDFs quedan en disco local con URL file://.
    for doc in body["documents"]:
        assert doc["blob_url"].startswith("file://")
    stored = list(tmp_path.rglob("*.pdf"))
    assert len(stored) == 2


def test_upload_rejects_invalid_pdf(client):
    r = client.post(
        "/api/v1/licitaciones/upload",
        data={"title": "Mala"},
        files={"pcap": ("pcap.pdf", b"esto no es un pdf", "application/pdf")},
    )
    assert r.status_code == 400
    assert "PDF" in r.json()["detail"]


def test_upload_rejects_oversized_pdf(client):
    from app.api.v1.endpoints import licitaciones as endpoint

    with patch.object(endpoint, "MAX_UPLOAD_BYTES", 10):
        r = client.post(
            "/api/v1/licitaciones/upload",
            data={"title": "Enorme"},
            files={"pcap": ("pcap.pdf", _pdf_bytes(), "application/pdf")},
        )
    assert r.status_code == 400
    assert "tamaño máximo" in r.json()["detail"]


def test_upload_requires_auth():
    # Sin override de get_current_user → 401.
    r = TestClient(app).post(
        "/api/v1/licitaciones/upload",
        data={"title": "x"},
        files={"pcap": ("p.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 401


def test_upload_pcap_only_no_orphan_rows(client):
    r = client.post(
        "/api/v1/licitaciones/upload",
        data={"title": "Solo PCAP"},
        files={"pcap": ("pcap.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 201
    docs = r.json()["documents"]
    assert [d["document_type"] for d in docs] == ["PCAP"]
