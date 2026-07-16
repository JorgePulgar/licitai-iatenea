"""Perfil de empresa (DM6): upsert único por usuario, serialización JSON y aislamiento."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.domain import CompanyProfile, User

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_perfil.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)

_BODY = {
    "name": "Iatenea SL",
    "description": "Consultora tecnológica",
    "sectors": ["TIC", "Consultoría"],
    "certifications": ["ISO 9001"],
    "employee_count": 12,
    "annual_revenue": "1,2 M€",
    "notable_clients": ["Ayto. de Madrid"],
    "solvency_tech": "5 proyectos similares",
    "solvency_econ": "Seguro RC 600k€",
}


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
def users(db):
    user_a = User(id="user-a", email="a@test.com", password_hash="x", is_active=True,
                  created_at=_NOW, updated_at=_NOW)
    user_b = User(id="user-b", email="b@test.com", password_hash="x", is_active=True,
                  created_at=_NOW, updated_at=_NOW)
    db.add_all([user_a, user_b])
    db.commit()
    return user_a, user_b


@pytest.fixture
def client_a(db, users):
    user_a, _ = users
    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user_a
    return TestClient(app)


def test_get_404_when_no_profile(client_a):
    r = client_a.get("/api/v1/perfil/")
    assert r.status_code == 404


def test_put_creates_profile_and_roundtrips_lists(client_a):
    r = client_a.put("/api/v1/perfil/", json=_BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Iatenea SL"
    assert data["sectors"] == ["TIC", "Consultoría"]
    assert data["notable_clients"] == ["Ayto. de Madrid"]
    assert data["is_default"] is True

    fetched = client_a.get("/api/v1/perfil/").json()
    assert fetched == data


def test_put_updates_existing_profile_in_place(client_a, db):
    first = client_a.put("/api/v1/perfil/", json=_BODY).json()

    updated_body = dict(_BODY, name="Iatenea 2 SL", sectors=[], employee_count=None)
    second = client_a.put("/api/v1/perfil/", json=updated_body).json()

    # Mismo perfil (upsert, no duplicado) con los campos actualizados/limpiados.
    assert second["id"] == first["id"]
    assert second["name"] == "Iatenea 2 SL"
    assert second["sectors"] == []
    assert second["employee_count"] is None
    assert db.query(CompanyProfile).count() == 1


def test_put_requires_name(client_a):
    r = client_a.put("/api/v1/perfil/", json={"description": "sin nombre"})
    assert r.status_code == 422


def test_isolation_user_a_never_sees_user_b_profile(client_a, db):
    db.add(CompanyProfile(
        id="prof-b", name="Empresa B", is_default=True, created_by="user-b",
        created_at=_NOW, updated_at=_NOW,
    ))
    db.commit()

    assert client_a.get("/api/v1/perfil/").status_code == 404

    created = client_a.put("/api/v1/perfil/", json=_BODY).json()
    assert created["id"] != "prof-b"
    # El perfil de B queda intacto.
    profile_b = db.query(CompanyProfile).filter_by(id="prof-b").one()
    assert profile_b.name == "Empresa B"
