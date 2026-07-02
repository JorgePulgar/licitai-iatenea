"""LIC-034 — summary caching: LLM called once; second call returns cached=True."""
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.db.base import Base
from app.db.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Licitacion, User
from app.models.schemas import SummaryResponse
from app.main import app

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_summary.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)

_FAKE_SUMMARY = SummaryResponse(
    licitacion_id="lic-1",
    objeto="Objeto del contrato de prueba",
    resumen="Resumen de prueba.",
)


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
def user_and_licitacion(db):
    user = User(id="user-1", email="u@test.com", password_hash="x", is_active=True,
                created_at=_NOW, updated_at=_NOW)
    lic = Licitacion(id="lic-1", user_id="user-1", title="Test Licitacion",
                     status="indexed", created_at=_NOW, updated_at=_NOW)
    db.add_all([user, lic])
    db.commit()
    return user, lic


@pytest.fixture
def client(db, user_and_licitacion):
    user, _ = user_and_licitacion
    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user
    with patch("app.api.v1.endpoints.licitaciones.SessionLocal", TestingSessionLocal):
        yield TestClient(app)


def test_summary_calls_llm_and_caches(client):
    with patch(
        "app.services.summary.generate_summary",
        new=AsyncMock(return_value=_FAKE_SUMMARY),
    ) as mock_generate:
        # First call — LLM invoked, result cached
        r1 = client.get("/api/v1/licitaciones/lic-1/summary")
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["objeto"] == "Objeto del contrato de prueba"
        assert data1["cached"] is False
        assert data1["generated_at"] is not None

        # Second call — cache hit, LLM NOT called again
        r2 = client.get("/api/v1/licitaciones/lic-1/summary")
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["cached"] is True
        assert data2["objeto"] == "Objeto del contrato de prueba"

        assert mock_generate.call_count == 1, "LLM must be called only once across two requests"


def test_summary_returns_409_when_not_indexed(db, user_and_licitacion):
    user, lic = user_and_licitacion
    lic.status = "processing"
    db.commit()

    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    response = client.get("/api/v1/licitaciones/lic-1/summary")
    assert response.status_code == 409


def test_summary_returns_404_for_other_user(db, user_and_licitacion):
    _, lic = user_and_licitacion
    other_user = User(id="other", email="other@test.com", password_hash="x", is_active=True,
                      created_at=_NOW, updated_at=_NOW)
    db.add(other_user)
    db.commit()

    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: other_user
    client = TestClient(app)

    response = client.get("/api/v1/licitaciones/lic-1/summary")
    assert response.status_code == 404
