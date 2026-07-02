"""
LIC-065 — Data isolation audit: verify user A cannot access data belonging to user B.
Tests cover GET, DELETE on /licitaciones, and AI Search filter verification.
"""
import asyncio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.db.base import Base
from app.db.database import get_db
from app.core.deps import get_current_user
from app.models.domain import Licitacion, User
from app.main import app

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_isolation.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)


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
def users_and_licitaciones(db):
    user_a = User(id="user-a", email="a@test.com", password_hash="x", is_active=True)
    user_b = User(id="user-b", email="b@test.com", password_hash="x", is_active=True)
    db.add_all([user_a, user_b])
    db.flush()

    lic_a = Licitacion(
        id="lic-a", user_id="user-a", title="Lic A",
        status="indexed", created_at=_NOW, updated_at=_NOW,
    )
    lic_b = Licitacion(
        id="lic-b", user_id="user-b", title="Lic B",
        status="indexed", created_at=_NOW, updated_at=_NOW,
    )
    db.add_all([lic_a, lic_b])
    db.commit()
    return user_a, user_b, lic_a, lic_b


def _client_as(db_session, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# ── GET isolation ─────────────────────────────────────────────────────────────

def test_get_returns_404_for_other_users_licitacion(db, users_and_licitaciones):
    user_a, user_b, lic_a, lic_b = users_and_licitaciones
    client = _client_as(db, user_a)
    response = client.get(f"/api/v1/licitaciones/{lic_b.id}")
    assert response.status_code == 404, "user_a must not see user_b's licitacion"


def test_get_returns_own_licitacion(db, users_and_licitaciones):
    user_a, user_b, lic_a, lic_b = users_and_licitaciones
    client = _client_as(db, user_a)
    response = client.get(f"/api/v1/licitaciones/{lic_a.id}")
    assert response.status_code == 200
    assert response.json()["id"] == "lic-a"


# ── LIST isolation ────────────────────────────────────────────────────────────

def test_list_returns_only_own_licitaciones(db, users_and_licitaciones):
    user_a, user_b, lic_a, lic_b = users_and_licitaciones
    client = _client_as(db, user_a)
    data = client.get("/api/v1/licitaciones/").json()
    ids = {item["id"] for item in data}
    assert "lic-a" in ids
    assert "lic-b" not in ids, "user_a must not see user_b's licitacion in list"


# ── DELETE isolation ──────────────────────────────────────────────────────────

def test_delete_returns_404_for_other_users_licitacion(db, users_and_licitaciones):
    user_a, user_b, lic_a, lic_b = users_and_licitaciones
    client = _client_as(db, user_a)
    response = client.delete(f"/api/v1/licitaciones/{lic_b.id}")
    assert response.status_code == 404, "user_a must not delete user_b's licitacion"


def test_delete_own_licitacion_succeeds(db, users_and_licitaciones):
    user_a, user_b, lic_a, lic_b = users_and_licitaciones
    client = _client_as(db, user_a)
    response = client.delete(f"/api/v1/licitaciones/{lic_a.id}")
    assert response.status_code == 204


# ── AI Search filter verification (unit) ─────────────────────────────────────

def test_hybrid_search_filter_contains_user_id(monkeypatch):
    """Verify hybrid_search always includes user_id in the AI Search filter string."""
    from app.services import query as query_module
    import asyncio

    captured_filter: list[str] = []

    class _FakeResult:
        def __iter__(self):
            return iter([])

    class _FakeClient:
        def search(self, **kwargs):
            captured_filter.append(kwargs.get("filter", ""))
            return _FakeResult()

    async def _fake_embed(text):
        return None

    monkeypatch.setattr(query_module, "_get_search_client", lambda: _FakeClient())
    monkeypatch.setattr(query_module, "embed_text", _fake_embed)

    asyncio.run(
        query_module.hybrid_search(
            query="test query",
            licitacion_id="lic-a",
            user_id="user-a",
        )
    )

    assert captured_filter, "search must have been called"
    filter_str = captured_filter[0]
    assert "user_id eq 'user-a'" in filter_str, (
        f"AI Search filter must include user_id. Got: {filter_str}"
    )
    assert "licitacion_id eq 'lic-a'" in filter_str, (
        f"AI Search filter must include licitacion_id. Got: {filter_str}"
    )
