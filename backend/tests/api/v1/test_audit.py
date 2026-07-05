"""
Tarea 1.6 / DM1 — GET /api/v1/system/audit protegido por rol admin.

Aceptación: sin autenticar → 401; autenticado no-admin → 403; admin → stats.
Verifica además que los agregados por usuario (queries agrupadas, sin N+1)
producen los mismos números que los datos sembrados.
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.domain import Licitacion, Pliego, Query, User

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_audit.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)

AUDIT_URL = "/api/v1/system/audit"


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


def _make_query_row(user_id: str, licitacion_id: str, tokens_prompt: int, tokens_completion: int) -> Query:
    return Query(
        id=str(uuid.uuid4()),
        licitacion_id=licitacion_id,
        user_id=user_id,
        question="¿Cuál es el plazo de presentación?",
        answer="No se encuentra en el pliego.",
        model_used="gpt-4o-mini",
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
        latency_ms=1200,
        created_at=_NOW,
    )


@pytest.fixture
def seeded_users(db):
    """Un admin sin actividad, un usuario con 2 licitaciones + 3 queries, un usuario sin nada."""
    admin = User(
        id="admin-1", email="admin@test.com", password_hash="x",
        role="admin", is_active=True,
    )
    heavy = User(
        id="user-heavy", email="heavy@test.com", password_hash="x",
        full_name="Heavy User", role="user", is_active=True,
    )
    idle = User(
        id="user-idle", email="idle@test.com", password_hash="x",
        role="user", is_active=False,
    )
    db.add_all([admin, heavy, idle])
    db.flush()

    lic_1 = Licitacion(
        id="lic-1", user_id="user-heavy", title="Lic 1",
        status="indexed", created_at=_NOW, updated_at=_NOW,
    )
    lic_2 = Licitacion(
        id="lic-2", user_id="user-heavy", title="Lic 2",
        status="processing", created_at=_NOW, updated_at=_NOW,
    )
    db.add_all([lic_1, lic_2])
    db.flush()

    db.add(Pliego(
        id="pli-1", licitacion_id="lic-1", document_type="PCAP",
        filename="pcap.pdf", blob_url="https://blob/x", blob_path="lic-1/pcap.pdf",
        size_bytes=2 * 1024 * 1024, mime_type="application/pdf",
        status="indexed", page_count=10,
    ))
    db.add_all([
        _make_query_row("user-heavy", "lic-1", 100, 50),
        _make_query_row("user-heavy", "lic-1", 200, 100),
        _make_query_row("user-heavy", "lic-2", 300, 150),
    ])
    db.commit()
    return admin, heavy, idle


def _client_as(db_session, user: User | None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_unauthenticated_returns_401(db):
    client = _client_as(db, None)
    response = client.get(AUDIT_URL)
    assert response.status_code == 401


def test_invalid_token_returns_401(db):
    client = _client_as(db, None)
    response = client.get(AUDIT_URL, headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


def test_non_admin_returns_403(db, seeded_users):
    _, heavy, _ = seeded_users
    client = _client_as(db, heavy)
    response = client.get(AUDIT_URL)
    assert response.status_code == 403


# ── Admin ─────────────────────────────────────────────────────────────────────

def test_admin_gets_stats(db, seeded_users):
    admin, _, _ = seeded_users
    client = _client_as(db, admin)
    response = client.get(AUDIT_URL)
    assert response.status_code == 200
    data = response.json()

    assert data["licitaciones"]["total"] == 2
    assert data["licitaciones"]["by_status"] == {"indexed": 1, "processing": 1}
    assert data["licitaciones"]["created_last_7d"] == 2

    assert data["documents"]["total_pliegos"] == 1
    assert data["documents"]["total_pages"] == 10
    assert data["documents"]["total_size_mb"] == 2.0
    assert data["documents"]["by_type"] == {"PCAP": 1}

    assert data["ai_usage"]["total_queries"] == 3
    assert data["ai_usage"]["total_tokens_prompt"] == 600
    assert data["ai_usage"]["total_tokens_completion"] == 300
    assert data["ai_usage"]["total_tokens"] == 900
    assert data["ai_usage"]["avg_latency_ms"] == 1200.0

    assert data["users"]["total_users"] == 3
    assert data["users"]["active_users"] == 2


def test_admin_user_activity_aggregates(db, seeded_users):
    """Los agregados agrupados por usuario cuadran; usuarios sin actividad salen a cero."""
    admin, _, _ = seeded_users
    client = _client_as(db, admin)
    activity = {
        row["user_id"]: row
        for row in client.get(AUDIT_URL).json()["user_activity"]
    }

    assert set(activity) == {"admin-1", "user-heavy", "user-idle"}

    heavy = activity["user-heavy"]
    assert heavy["email"] == "heavy@test.com"
    assert heavy["full_name"] == "Heavy User"
    assert heavy["licitaciones_count"] == 2
    assert heavy["queries_count"] == 3
    assert heavy["tokens_total"] == 900

    for idle_id in ("admin-1", "user-idle"):
        assert activity[idle_id]["licitaciones_count"] == 0
        assert activity[idle_id]["queries_count"] == 0
        assert activity[idle_id]["tokens_total"] == 0


def test_empty_database_returns_zeroed_stats(db):
    admin = User(
        id="admin-solo", email="solo@test.com", password_hash="x",
        role="admin", is_active=True,
    )
    db.add(admin)
    db.commit()

    client = _client_as(db, admin)
    data = client.get(AUDIT_URL).json()

    assert data["licitaciones"]["total"] == 0
    assert data["documents"]["total_pliegos"] == 0
    assert data["ai_usage"]["total_queries"] == 0
    assert data["ai_usage"]["avg_latency_ms"] is None
    assert data["memorias"]["total_documents"] == 0
    assert len(data["user_activity"]) == 1
