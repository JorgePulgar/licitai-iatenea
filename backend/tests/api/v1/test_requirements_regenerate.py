"""
Tarea 5.5 / DM4 — endpoint POST /licitaciones/{id}/requirements/regenerate.

Invalida la cache y re-extrae. Aislamiento y estados igual que el GET.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.domain import Licitacion, PliegoRequirement, User

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_requirements_regenerate.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)

URL = "/api/v1/licitaciones/lic-1/requirements/regenerate"


@pytest.fixture(autouse=True)
def clean_overrides():
    yield
    app.dependency_overrides.clear()


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
def client(db):
    user = User(id="user-1", email="u@test.com", password_hash="x", is_active=True)
    lic = Licitacion(id="lic-1", user_id="user-1", title="Test",
                     status="indexed", created_at=_NOW, updated_at=_NOW)
    stale = PliegoRequirement(
        id="req-stale", licitacion_id="lic-1", categoria="tecnico",
        descripcion="Requisito obsoleto", documento_origen="pcap",
        es_obligatorio=True, generated_at=_NOW,
    )
    db.add_all([user, lic, stale])
    db.commit()

    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user
    with patch("app.api.v1.endpoints.licitaciones.SessionLocal", TestingSessionLocal):
        yield TestClient(app)


def test_regenerate_invalidates_cache_and_reextracts(client, db):
    # Sin Azure configurado (conftest) y sin chunks, la re-extracción devuelve vacío:
    # lo relevante es que la cache vieja desaparece y la respuesta no es cached.
    with patch("app.services.requirements.hybrid_search", new=AsyncMock(return_value=[])):
        response = client.post(URL)

    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is False
    assert data["requirements"] == []
    assert db.query(PliegoRequirement).count() == 0, "la cache obsoleta debe borrarse"


def test_regenerate_404_for_foreign_licitacion(client, db):
    db.add_all([
        User(id="user-2", email="b@test.com", password_hash="x", is_active=True),
        Licitacion(id="lic-2", user_id="user-2", title="Ajena",
                   status="indexed", created_at=_NOW, updated_at=_NOW),
    ])
    db.commit()

    response = client.post("/api/v1/licitaciones/lic-2/requirements/regenerate")
    assert response.status_code == 404


def test_regenerate_409_when_not_indexed(client, db):
    lic = db.query(Licitacion).filter(Licitacion.id == "lic-1").one()
    lic.status = "processing"
    db.commit()

    assert client.post(URL).status_code == 409
