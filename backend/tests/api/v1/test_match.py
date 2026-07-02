"""Match score v2 — uses persisted CompanyProfile + extracted requirements."""
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
from app.models.domain import CompanyProfile, Licitacion, User
from app.models.schemas import MatchResponse, RequirementsListResponse
from app.main import app

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_match.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)

_FAKE_MATCH = MatchResponse(
    licitacion_id="lic-1",
    puntuacion_total=75,
    nivel_encaje="Alto",
    resumen="Encaje alto.",
    desglose=[],
    requisitos_evaluados=[],
)

_FAKE_REQS = RequirementsListResponse(
    licitacion_id="lic-1",
    requirements=[],
    cached=True,
    generated_at=_NOW,
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
def profile(db, user_and_licitacion):
    user, _ = user_and_licitacion
    p = CompanyProfile(
        id="profile-1",
        name="Test Company",
        description="A test company",
        certifications=json.dumps(["ISO 9001"]),
        employee_count=50,
        annual_revenue="5M €",
        is_default=True,
        created_by=user.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    db.add(p)
    db.commit()
    return p


@pytest.fixture
def client(db, user_and_licitacion, profile):
    user, _ = user_and_licitacion
    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user
    with patch("app.api.v1.endpoints.licitaciones.SessionLocal", TestingSessionLocal):
        yield TestClient(app)


def test_match_returns_400_without_profile(db, user_and_licitacion):
    """Match should fail if no company profile exists."""
    user, _ = user_and_licitacion
    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    response = c.post("/api/v1/licitaciones/lic-1/match")
    assert response.status_code == 400
    assert "perfil de empresa" in response.json()["detail"].lower()


def test_match_with_profile_calls_calculate(client):
    with patch(
        "app.services.match.calculate_match",
        new=AsyncMock(return_value=_FAKE_MATCH),
    ), patch(
        "app.services.requirements.extract_requirements",
        new=AsyncMock(return_value=_FAKE_REQS),
    ):
        response = client.post("/api/v1/licitaciones/lic-1/match")
        assert response.status_code == 200
        data = response.json()
        assert data["puntuacion_total"] == 75
        assert data["nivel_encaje"] == "Alto"


def test_match_returns_409_when_not_indexed(db, user_and_licitacion, profile):
    user, lic = user_and_licitacion
    lic.status = "processing"
    db.commit()

    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    response = c.post("/api/v1/licitaciones/lic-1/match")
    assert response.status_code == 409


def test_compute_profile_hash_deterministic():
    from app.services.match import compute_profile_hash
    p = CompanyProfile(
        id="p1", name="Test", description="Desc", certifications='["ISO"]',
        employee_count=10, annual_revenue="1M", is_default=True,
        created_by="u1", created_at=_NOW, updated_at=_NOW,
    )
    h1 = compute_profile_hash(p)
    h2 = compute_profile_hash(p)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_profile_hash_changes_on_update():
    from app.services.match import compute_profile_hash
    p = CompanyProfile(
        id="p1", name="Test", description="Desc",
        is_default=True, created_by="u1", created_at=_NOW, updated_at=_NOW,
    )
    h1 = compute_profile_hash(p)
    p.name = "Updated"
    h2 = compute_profile_hash(p)
    assert h1 != h2
