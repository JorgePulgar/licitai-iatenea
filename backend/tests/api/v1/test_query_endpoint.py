"""
Tarea 1.7 / DM2 — reescritura de endpoints/query.py.

Aceptación: telemetría (tokens_prompt, tokens_completion, latency_ms) persistida
en cada consulta; fallo de persistencia loggeado (no silencioso) sin tumbar la
respuesta; endpoint de sesiones en 2 queries máximo; historial paginado.

El comportamiento de sesiones/memoria ya lo cubre test_query_sessions.py (intacto).
"""
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.domain import Licitacion, Query, User
from app.models.schemas import Citation, QueryResponse

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_query_endpoint.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)

QUERY_URL = "/api/v1/query/"


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
    user = User(id="user-a", email="a@test.com", password_hash="x", is_active=True)
    lic = Licitacion(
        id="lic-a", user_id="user-a", title="Licitación A",
        status="indexed", created_at=_NOW, updated_at=_NOW,
    )
    db.add_all([user, lic])
    db.commit()

    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)


def _citation(page: int) -> Citation:
    return Citation(
        content="fragmento", page_number=page, pliego_id="pli-1",
        licitacion_id="lic-a", filename="pcap.pdf", document_type="pcap",
    )


def _ask(client, question="¿Plazo?", session_id="sess-1"):
    return client.post(QUERY_URL, json={
        "question": question,
        "licitacion_id": "lic-a",
        "session_id": session_id,
    })


# ── Telemetría persistida (aceptación 1.7) ────────────────────────────────────

def test_telemetry_columns_populated_on_every_query(client, db):
    fake = AsyncMock(return_value=QueryResponse(
        answer="Respuesta [pcap p. 3].",
        citations=[_citation(3)],
        tokens_prompt=123,
        tokens_completion=45,
    ))
    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        assert _ask(client).status_code == 200

    row = db.query(Query).one()
    assert row.tokens_prompt == 123
    assert row.tokens_completion == 45
    assert row.latency_ms is not None and row.latency_ms >= 0
    assert row.had_citations is True
    assert row.is_unanswerable is False


def test_telemetry_fields_never_reach_the_client(client):
    """tokens_* son internos (exclude=True): no aparecen en el JSON de respuesta."""
    fake = AsyncMock(return_value=QueryResponse(
        answer="r", citations=[], tokens_prompt=10, tokens_completion=5,
    ))
    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        data = _ask(client).json()
    assert "tokens_prompt" not in data
    assert "tokens_completion" not in data


def test_unanswerable_turn_flags_persisted(client, db):
    fake = AsyncMock(return_value=QueryResponse(
        answer="No he encontrado información sobre esto en el pliego.",
        citations=[], tokens_prompt=80, tokens_completion=20,
    ))
    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        assert _ask(client).status_code == 200

    row = db.query(Query).one()
    assert row.had_citations is False
    assert row.is_unanswerable is True
    assert row.tokens_prompt == 80


# ── Fallo de persistencia: loggeado, nunca silencioso ────────────────────────

def test_persistence_failure_logged_and_answer_still_returned(client, db, caplog):
    fake = AsyncMock(return_value=QueryResponse(answer="r", citations=[]))
    original_commit = db.commit

    def failing_commit():
        raise RuntimeError("DB down")

    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        db.commit = failing_commit
        try:
            with caplog.at_level(logging.ERROR, logger="app.api.v1.endpoints.query"):
                response = _ask(client)
        finally:
            db.commit = original_commit

    assert response.status_code == 200
    assert response.json()["answer"] == "r"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors, "persistence failure must be logged as ERROR, never swallowed"
    assert errors[0].exc_info is not None


# ── Sesiones: 2 queries máximo ────────────────────────────────────────────────

def test_sessions_endpoint_uses_at_most_two_queries(client, db):
    fake = AsyncMock(return_value=QueryResponse(answer="r", citations=[]))
    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        for session in ("s1", "s2", "s3"):
            _ask(client, question=f"Primera de {session}", session_id=session)
            _ask(client, question=f"Segunda de {session}", session_id=session)

    selects: list[str] = []

    def count_selects(conn, cursor, statement, parameters, context, executemany):
        # El refresh del objeto User expirado (fixture tras commits) no es lógica
        # del endpoint; solo cuentan las queries sobre licitaciones/queries.
        if statement.lstrip().upper().startswith("SELECT") and "FROM users" not in statement:
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        response = client.get("/api/v1/query/lic-a/sessions")
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert response.status_code == 200
    assert len(selects) <= 2, f"expected <=2 SELECTs, got {len(selects)}:\n" + "\n".join(selects)

    sessions = {s["session_id"]: s for s in response.json()}
    assert set(sessions) == {"s1", "s2", "s3"}
    assert sessions["s2"]["title"] == "Primera de s2"
    assert sessions["s2"]["message_count"] == 2


# ── Historial paginado ────────────────────────────────────────────────────────

def test_history_pagination(client):
    fake = AsyncMock(return_value=QueryResponse(answer="r", citations=[]))
    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        for i in range(5):
            _ask(client, question=f"Pregunta {i}", session_id="sess-1")

    page_1 = client.get("/api/v1/query/lic-a/history?limit=2&offset=0").json()
    page_2 = client.get("/api/v1/query/lic-a/history?limit=2&offset=2").json()
    page_3 = client.get("/api/v1/query/lic-a/history?limit=2&offset=4").json()

    assert [h["question"] for h in page_1] == ["Pregunta 0", "Pregunta 1"]
    assert [h["question"] for h in page_2] == ["Pregunta 2", "Pregunta 3"]
    assert [h["question"] for h in page_3] == ["Pregunta 4"]


def test_history_limit_validation(client):
    assert client.get("/api/v1/query/lic-a/history?limit=0").status_code == 422
    assert client.get("/api/v1/query/lic-a/history?limit=501").status_code == 422
    assert client.get("/api/v1/query/lic-a/history?offset=-1").status_code == 422


def test_history_default_returns_all_recent_turns(client):
    """Sin params, el historial completo de una conversación normal cabe en el default."""
    fake = AsyncMock(return_value=QueryResponse(answer="r", citations=[]))
    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        for i in range(3):
            _ask(client, question=f"P{i}")

    items = client.get("/api/v1/query/lic-a/history").json()
    assert len(items) == 3


# ── Aislamiento básico del rewrite (no regresión) ─────────────────────────────

def test_history_of_foreign_licitacion_is_404(client, db):
    other = User(id="user-b", email="b@test.com", password_hash="x", is_active=True)
    lic_b = Licitacion(
        id="lic-b", user_id="user-b", title="Ajena",
        status="indexed", created_at=_NOW, updated_at=_NOW,
    )
    db.add_all([other, lic_b])
    db.commit()

    assert client.get("/api/v1/query/lic-b/history").status_code == 404
    assert client.get("/api/v1/query/lic-b/sessions").status_code == 404


def test_query_on_unindexed_licitacion_is_409(client, db):
    db.add(Licitacion(
        id="lic-proc", user_id="user-a", title="Procesando",
        status="processing", created_at=_NOW, updated_at=_NOW,
    ))
    db.commit()

    response = client.post(QUERY_URL, json={
        "question": "¿?", "licitacion_id": "lic-proc",
    })
    assert response.status_code == 409
