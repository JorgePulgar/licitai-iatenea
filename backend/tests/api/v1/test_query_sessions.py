"""Chat de consultas (RAG) — sesiones persistidas y memoria acotada por hilo.

Cubre: persistencia de `session_id`, historial filtrado por sesión, listado de
hilos y que la memoria reinyectada al LLM se limite a la sesión activa.
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
from app.models.domain import Licitacion, User
from app.models.schemas import QueryResponse

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_query_sessions.db"
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
def client(db):
    user = User(id="user-a", email="a@test.com", password_hash="x", is_active=True,
                created_at=_NOW, updated_at=_NOW)
    lic = Licitacion(id="lic-a", user_id="user-a", title="Licitación A",
                     status="indexed", created_at=_NOW, updated_at=_NOW)
    db.add_all([user, lic])
    db.commit()

    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)


def _ask(client, question, session_id):
    return client.post("/api/v1/query/", json={
        "question": question,
        "licitacion_id": "lic-a",
        "session_id": session_id,
    })


def test_history_is_scoped_per_session(client):
    fake = AsyncMock(return_value=QueryResponse(answer="respuesta", citations=[]))
    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        assert _ask(client, "Hola sesión A", "sess-a").status_code == 200
        assert _ask(client, "Segunda de A", "sess-a").status_code == 200
        assert _ask(client, "Hola sesión B", "sess-b").status_code == 200

    # El historial de A solo trae los turnos de A, en orden.
    hist_a = client.get("/api/v1/query/lic-a/history?session_id=sess-a").json()
    assert [h["question"] for h in hist_a] == ["Hola sesión A", "Segunda de A"]
    # El de B, solo el suyo.
    hist_b = client.get("/api/v1/query/lic-a/history?session_id=sess-b").json()
    assert [h["question"] for h in hist_b] == ["Hola sesión B"]


def test_sessions_endpoint_lists_threads(client):
    fake = AsyncMock(return_value=QueryResponse(answer="r", citations=[]))
    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake):
        _ask(client, "Primera de A", "sess-a")
        _ask(client, "Segunda de A", "sess-a")
        _ask(client, "Única de B", "sess-b")

    sessions = client.get("/api/v1/query/lic-a/sessions").json()
    by_id = {s["session_id"]: s for s in sessions}
    assert set(by_id) == {"sess-a", "sess-b"}
    # El rótulo es la primera pregunta del hilo; el contador, sus turnos.
    assert by_id["sess-a"]["title"] == "Primera de A"
    assert by_id["sess-a"]["message_count"] == 2
    assert by_id["sess-b"]["message_count"] == 1


def test_memory_reinjected_is_limited_to_active_session(client):
    """La pregunta de seguimiento de B no recibe los turnos de A como memoria."""
    captured: dict[str, list] = {}

    async def fake_query(*args, **kwargs):
        captured["history"] = kwargs.get("history")
        return QueryResponse(answer="r", citations=[])

    with patch("app.api.v1.endpoints.query.query_licitacion", new=fake_query):
        _ask(client, "Algo en A", "sess-a")
        _ask(client, "Primera en B", "sess-b")   # nueva sesión: sin memoria previa
        assert captured["history"] == []
        _ask(client, "Seguimiento en B", "sess-b")
        # Solo el turno previo de B, no el de A.
        assert captured["history"] == [("Primera en B", "r")]
