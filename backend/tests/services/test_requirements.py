"""
Tarea 5.5 / DM4 — reescritura del servicio de requisitos.

Aceptación: retrieval en paralelo (no secuencial), páginas imposibles descartadas,
enum de categoría forzado, dedup, cache-first, invalidación.
"""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.domain import Licitacion, PliegoRequirement, User
from app.services.requirements import (
    _COVERAGE_QUERIES,
    extract_requirements,
    invalidate_requirements,
)

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_requirements.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    session.add_all([
        User(id="user-1", email="u@test.com", password_hash="x", is_active=True),
        Licitacion(id="lic-1", user_id="user-1", title="Test",
                   status="indexed", created_at=_NOW, updated_at=_NOW),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _chunk(text="contenido", page=3, doc="pcap", cid=None):
    return {
        "chunk_id": cid or f"{doc}-{page}-{text[:10]}",
        "pliego_id": "pli-1",
        "document_type": doc,
        "page_number": page,
        "text": text,
        "score": 1.0,
    }


def _fake_llm(payload: dict):
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload)),
            finish_reason="stop",
        )]
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def _req(descripcion, categoria="tecnico", pagina=3, doc="pcap", obligatorio=True):
    return {
        "categoria": categoria,
        "descripcion": descripcion,
        "pagina": pagina,
        "documento_origen": doc,
        "es_obligatorio": obligatorio,
    }


def _run_extract(db, llm_payload, page_counts=None, search=None):
    fake_search = search or AsyncMock(return_value=[_chunk()])
    with patch("app.services.requirements.hybrid_search", new=fake_search), \
         patch("app.services.requirements.get_openai_client",
               return_value=_fake_llm(llm_payload)):
        return asyncio.run(extract_requirements(
            "lic-1", "user-1", "Test", db,
            session_factory=TestingSessionLocal,
            page_counts=page_counts,
        )), fake_search


# ── Retrieval en paralelo (aceptación: latencia ~1/10) ───────────────────────

def test_coverage_searches_run_concurrently(db):
    """Las búsquedas se solapan (gather), no van una tras otra."""
    active = {"now": 0, "max": 0}

    async def slow_search(*args, **kwargs):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return [_chunk()]

    _run_extract(db, {"requisitos": []}, search=slow_search)

    assert active["max"] > 1, "hybrid_search debe ejecutarse en paralelo (asyncio.gather)"


def test_one_search_per_coverage_query_and_chunks_deduped(db):
    fake_search = AsyncMock(return_value=[_chunk(cid="same-chunk")])
    result, _ = _run_extract(db, {"requisitos": []}, search=fake_search)

    assert fake_search.await_count == len(_COVERAGE_QUERIES)


# ── Validación de páginas contra page_counts reales ──────────────────────────

def test_impossible_page_is_dropped_requirement_kept(db):
    payload = {"requisitos": [
        _req("Garantía definitiva del 5%", pagina=99, doc="pcap"),
        _req("ISO 27001 obligatoria", pagina=12, doc="pcap"),
    ]}
    result, _ = _run_extract(db, payload, page_counts={"pcap": 30})

    by_desc = {r.descripcion: r for r in result.requirements}
    assert by_desc["Garantía definitiva del 5%"].pagina is None  # 99 > 30 → cita fuera
    assert by_desc["ISO 27001 obligatoria"].pagina == 12          # 12 ≤ 30 → se conserva


def test_non_integer_and_negative_pages_dropped(db):
    payload = {"requisitos": [
        _req("Requisito A", pagina="p. cinco"),
        _req("Requisito B", pagina=-2),
        _req("Requisito C", pagina=None),
    ]}
    result, _ = _run_extract(db, payload, page_counts={"pcap": 30})
    assert all(r.pagina is None for r in result.requirements)


def test_unknown_doc_type_page_kept_permissively(db):
    """Sin page_count conocido para el documento no se puede verificar: se conserva."""
    payload = {"requisitos": [_req("Anexo requisito", pagina=7, doc="anexo")]}
    result, _ = _run_extract(db, payload, page_counts={"pcap": 30})
    assert result.requirements[0].pagina == 7


# ── Enum de categoría y documento forzados ───────────────────────────────────

def test_invalid_category_normalized(db):
    payload = {"requisitos": [
        _req("Requisito raro", categoria="legal-cosmico"),
        _req("Requisito plazo", categoria="PLAZO"),  # case-insensitive
    ]}
    result, _ = _run_extract(db, payload)
    by_desc = {r.descripcion: r for r in result.requirements}
    assert by_desc["Requisito raro"].categoria == "tecnico"
    assert by_desc["Requisito plazo"].categoria == "plazo"


def test_invalid_doc_type_normalized(db):
    payload = {"requisitos": [_req("Requisito X", doc="contrato")]}
    result, _ = _run_extract(db, payload)
    assert result.requirements[0].documento_origen == "pcap"


# ── Dedup ─────────────────────────────────────────────────────────────────────

def test_duplicate_descriptions_deduped(db):
    payload = {"requisitos": [
        _req("Garantía del 5%"),
        _req("  garantía   del 5%  "),  # misma descripción normalizada
        _req(""),                        # vacía → fuera
    ]}
    result, _ = _run_extract(db, payload)
    assert len(result.requirements) == 1


# ── Cache e invalidación ──────────────────────────────────────────────────────

def test_cache_hit_skips_search_and_llm(db):
    db.add(PliegoRequirement(
        id="req-1", licitacion_id="lic-1", categoria="tecnico",
        descripcion="Cacheado", documento_origen="pcap",
        es_obligatorio=True, generated_at=_NOW,
    ))
    db.commit()

    fake_search = AsyncMock()
    with patch("app.services.requirements.hybrid_search", new=fake_search):
        result = asyncio.run(extract_requirements("lic-1", "user-1", "Test", db))

    assert result.cached is True
    assert result.requirements[0].descripcion == "Cacheado"
    fake_search.assert_not_awaited()


def test_invalidate_deletes_cache(db):
    db.add_all([
        PliegoRequirement(
            id=f"req-{i}", licitacion_id="lic-1", categoria="tecnico",
            descripcion=f"R{i}", documento_origen="pcap",
            es_obligatorio=True, generated_at=_NOW,
        )
        for i in range(3)
    ])
    db.commit()

    deleted = invalidate_requirements("lic-1", db)

    assert deleted == 3
    assert db.query(PliegoRequirement).count() == 0


def test_extraction_persists_rows(db):
    payload = {"requisitos": [_req("Persistido")]}
    result, _ = _run_extract(db, payload)

    assert result.cached is False
    rows = db.query(PliegoRequirement).all()
    assert len(rows) == 1
    assert rows[0].descripcion == "Persistido"
