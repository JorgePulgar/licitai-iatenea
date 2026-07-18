"""Memoria Técnica (flujo completo, ADR-002) — endpoints + servicio.

Cubre: esquema (grounding + ramas), propuesta (Markdown), chat de edición con
histórico, export PDF, lectura de documento, CRUD de secciones, aislamiento
per-usuario y derive_template.
"""
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.deps import get_current_user
from app.db.base import Base
from app.db.database import get_db
from app.main import app
from app.models.domain import Licitacion, MemoriaSection, PliegoRequirement, User

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_memoria.db"
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
    user_a = User(id="user-a", email="a@test.com", password_hash="x", is_active=True,
                  created_at=_NOW, updated_at=_NOW)
    user_b = User(id="user-b", email="b@test.com", password_hash="x", is_active=True,
                  created_at=_NOW, updated_at=_NOW)
    lic_a = Licitacion(id="lic-a", user_id="user-a", title="Licitación A",
                       status="indexed", created_at=_NOW, updated_at=_NOW)
    lic_b = Licitacion(id="lic-b", user_id="user-b", title="Licitación B",
                       status="indexed", created_at=_NOW, updated_at=_NOW)
    db.add_all([user_a, user_b, lic_a, lic_b])
    db.commit()
    return user_a, user_b, lic_a, lic_b


def _section(id_, lic_id, user_id, title, order=0, status="accepted"):
    return MemoriaSection(
        id=id_, licitacion_id=lic_id, user_id=user_id, title=title,
        sort_order=order, status=status, source="user",
        created_at=_NOW, updated_at=_NOW,
    )


@pytest.fixture
def client_a(db, users_and_licitaciones):
    """Cliente autenticado como user_a, con la escritura fresca apuntando al engine de test."""
    user_a, *_ = users_and_licitaciones
    app.dependency_overrides[get_db] = lambda: (yield db)
    app.dependency_overrides[get_current_user] = lambda: user_a
    with patch("app.api.v1.endpoints.memoria.SessionLocal", TestingSessionLocal):
        yield TestClient(app)


def _fake_openai_json(payload: dict):
    """Cliente OpenAI falso que devuelve JSON (esquema / chat)."""
    content = json.dumps(payload)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def _fake_openai_text(text: str):
    """Cliente OpenAI falso que devuelve texto plano (propuesta Markdown)."""
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def _create_memoria(client: TestClient, markdown: str = "# Memoria\n\nContenido.") -> dict:
    fake = _fake_openai_text(markdown)
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        response = client.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": []},
        )
    assert response.status_code == 200
    return response.json()


# ── Fase 1: esquema (JSON v2, spec-memoria-prompts §1) ───────────────────────

def test_esquema_extracts_structure_from_v2_json(client_a):
    fake = _fake_openai_json({
        "estructura_impuesta": True,
        "limite_total_paginas": 40,
        "apartados": [
            {"numero": "1", "titulo": "Plan de trabajo", "criterio": "Metodología",
             "peso": "40 puntos", "limite": "10 páginas", "fuente_pagina": 12},
            {"numero": "2", "titulo": "Equipo", "criterio": None,
             "peso": None, "limite": None, "fuente_pagina": None},
        ],
    })
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        r = client_a.post("/api/v1/licitaciones/lic-a/memoria/esquema",
                          json={"message": "Propón las secciones"})
    assert r.status_code == 200
    data = r.json()
    # Mapeo v2 → contrato del producto: numeración en el título, peso/límite numéricos.
    assert [s["title"] for s in data["esquema"]] == ["1. Plan de trabajo", "2. Equipo"]
    first = data["esquema"][0]
    assert first["criterio_adjudicacion"] == "Metodología"
    assert first["max_puntos"] == 40.0
    assert first["page_budget"] == 10
    assert "[p. 12]" in first["description"]
    # El reply se construye en código (el JSON v2 no lo trae).
    assert "estructura" in data["reply"].lower()
    assert "40" in data["reply"]  # límite total de páginas
    # El esquema no persiste secciones ni historial de chat.
    assert client_a.get("/api/v1/licitaciones/lic-a/memoria/sections").json() == []
    assert client_a.get("/api/v1/licitaciones/lic-a/memoria/chat").json() == []


def test_esquema_grounding_fenced_and_uses_extracted_criterios(client_a, db):
    db.add(PliegoRequirement(
        id="req-1", licitacion_id="lic-a", categoria="criterio_adjudicacion",
        descripcion="Memoria técnica — máximo 50 puntos (juicio de valor)",
        pagina=12, documento_origen="pcap", es_obligatorio=False, generated_at=_NOW,
    ))
    db.commit()
    fake = _fake_openai_json({"estructura_impuesta": False, "apartados": [
        {"numero": None, "titulo": "Memoria técnica"},
    ]})
    search_mock = AsyncMock(return_value=[])
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=search_mock):
        r = client_a.post("/api/v1/licitaciones/lic-a/memoria/esquema", json={"message": "go"})
    assert r.status_code == 200
    # Con criterios ya extraídos solo se busca la estructura en el PPT (1 llamada,
    # sin fallback de criterios sobre el PCAP).
    assert search_mock.call_count == 1
    assert search_mock.call_args.kwargs.get("document_type") == "ppt"
    # Los criterios van al LLM DENTRO del fence (datos no confiables, 1.8).
    sent = fake.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    fenced = sent.split("<fragmentos_pliego>")[1].split("</fragmentos_pliego>")[0]
    assert "máximo 50 puntos" in fenced


def test_esquema_isolation(client_a):
    r = client_a.post("/api/v1/licitaciones/lic-b/memoria/esquema", json={"message": "x"})
    assert r.status_code == 404


# ── Fase 2: propuesta (Markdown) ───────────────────────────────────────────────

def test_propuesta_generates_and_persists(client_a):
    section_md = "## Plan de trabajo\n\nContenido."
    fake = _fake_openai_router(lambda user: section_md, intro_text="Resumen de la propuesta.")
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        r = client_a.post("/api/v1/licitaciones/lic-a/memoria/propuesta",
                          json={"esquema": [{"title": "Plan de trabajo", "sort_order": 0}]})
    assert r.status_code == 200
    md = r.json()["markdown"]
    # Cosido determinista: # título de la licitación, introducción y sección verbatim.
    assert md.startswith("# Licitación A")
    assert "Resumen de la propuesta." in md
    assert section_md in md
    # Persistido en el documento.
    doc_id = r.json()["doc_id"]
    doc = client_a.get(
        f"/api/v1/licitaciones/lic-a/memoria/documents/{doc_id}"
    ).json()
    assert doc["markdown"] == md


def test_propuesta_isolation(client_a):
    r = client_a.post("/api/v1/licitaciones/lic-b/memoria/propuesta", json={"esquema": []})
    assert r.status_code == 404


# ── Fase 2b: redacción multi-agente (fan-out) ─────────────────────────────────

_SECTION_TITLE_RE = re.compile(r'Redacta el apartado "([^"]+)"')

# Rasgo distintivo del prompt de sección v2 formateado (spec-MP §2).
_SECTION_PROMPT_MARK = "redactor senior de memorias técnicas"


def _section_title_from_system(system: str) -> str:
    return _SECTION_TITLE_RE.search(system).group(1)


def _fake_openai_router(section_fn, intro_text="Introducción global de la memoria."):
    """
    Cliente OpenAI falso que enruta por system prompt:
      - agente de sección (prompt v2 formateado) → section_fn(system_formateado)
      - agente de introducción                   → intro_text
    Permite distinguir las llamadas de fan-out de la de introducción. El cosido del
    documento es determinista en código (no pasa por el LLM).
    """
    from app.prompts.memoria import MEMORIA_INTRO_PROMPT

    def create(*, messages, **kwargs):
        system = messages[0]["content"]
        if _SECTION_PROMPT_MARK in system:
            content = section_fn(system)
        elif system == MEMORIA_INTRO_PROMPT:
            content = intro_text
        else:
            content = "{}"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=create)
    return client


def _system_prompts_used(fake) -> list[str]:
    return [c.kwargs["messages"][0]["content"] for c in fake.chat.completions.create.call_args_list]


def test_propuesta_fans_out_one_agent_per_section_then_stitches(client_a):
    """N secciones → N agentes de sección + 1 agente de introducción; cosido determinista."""
    from app.prompts.memoria import MEMORIA_INTRO_PROMPT

    def section_fn(system):
        # Devuelve el título recibido para verificar el routing por sección.
        title = _section_title_from_system(system)
        return f"## {title}\n\nCuerpo de {title}."

    fake = _fake_openai_router(section_fn, intro_text="Introducción de la memoria.")
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        r = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": [
                {"title": "Plan de trabajo", "sort_order": 0},
                {"title": "Equipo", "sort_order": 1},
            ]},
        )
    assert r.status_code == 200
    # 2 agentes de sección + 1 de introducción (el cosido NO usa LLM).
    systems = _system_prompts_used(fake)
    assert sum(1 for s in systems if _SECTION_PROMPT_MARK in s) == 2
    assert systems.count(MEMORIA_INTRO_PROMPT) == 1
    # El documento cose, verbatim y en orden, las secciones bajo el título y la intro.
    md = r.json()["markdown"]
    assert md.startswith("# Licitación A")
    assert "Introducción de la memoria." in md
    assert "Cuerpo de Plan de trabajo." in md
    assert "Cuerpo de Equipo." in md
    assert md.index("Plan de trabajo") < md.index("Equipo")


def test_section_agent_receives_only_its_relevant_requisitos(client_a, db):
    """Los requisitos se reparten por solapamiento léxico: cada sección ve los suyos."""
    db.add_all([
        PliegoRequirement(
            id="req-plan", licitacion_id="lic-a", categoria="tecnico",
            descripcion="El plan de trabajo debe incluir un cronograma detallado",
            pagina=5, documento_origen="ppt", es_obligatorio=True, generated_at=_NOW,
        ),
        PliegoRequirement(
            id="req-equipo", licitacion_id="lic-a", categoria="tecnico",
            descripcion="El equipo adscrito requiere certificación PMP",
            pagina=7, documento_origen="ppt", es_obligatorio=True, generated_at=_NOW,
        ),
    ])
    db.commit()

    captured: dict[str, str] = {}

    def section_fn(system):
        captured[_section_title_from_system(system)] = system
        return "## x\n\nbody"

    fake = _fake_openai_router(section_fn)
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        r = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": [
                {"title": "Plan de trabajo", "sort_order": 0},
                {"title": "Equipo", "sort_order": 1},
            ]},
        )
    assert r.status_code == 200
    assert "cronograma detallado" in captured["Plan de trabajo"]
    assert "certificación PMP" not in captured["Plan de trabajo"]
    assert "certificación PMP" in captured["Equipo"]
    assert "cronograma detallado" not in captured["Equipo"]


def test_propuesta_degrades_failed_section_without_aborting(client_a):
    """Si un agente de sección falla, se degrada con marcador y el documento se produce igual."""
    from app.prompts.memoria import MEMORIA_INTRO_PROMPT
    from app.services.memoria import SECTION_FAILURE_MARKER

    def create(*, messages, **kwargs):
        system = messages[0]["content"]
        if _SECTION_PROMPT_MARK in system:
            if _section_title_from_system(system) == "Equipo":
                raise RuntimeError("LLM 500")
            content = "## Plan de trabajo\n\nBien."
        elif system == MEMORIA_INTRO_PROMPT:
            content = "Introducción."
        else:
            content = "{}"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(side_effect=create)

    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        r = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": [
                {"title": "Plan de trabajo", "sort_order": 0},
                {"title": "Equipo", "sort_order": 1},
            ]},
        )
    assert r.status_code == 200
    md = r.json()["markdown"]
    assert "Bien." in md                       # la sección buena sobrevive
    assert SECTION_FAILURE_MARKER in md         # la fallida se degrada, no aborta


def test_section_markdown_is_normalized_for_consistent_rendering(client_a):
    """
    El cosido determinista normaliza el estilo de cada agente: quita fences que
    envolverían la sección (se renderizarían como código), degrada encabezados de
    nivel 1 a nivel 2 y garantiza un único «#» de documento. Así todas las secciones
    quedan con la misma jerarquía y el Markdown se interpreta bien.
    """
    def section_fn(system):
        if _section_title_from_system(system) == "Equipo":
            # Agente que envuelve TODO en un fence ```markdown (rompería el render).
            return "```markdown\n## Equipo\n\n**Perfiles** del equipo.\n```"
        # Agente que usa un nivel 1 (#) en vez de 2.
        return "# Plan de trabajo\n\nFases del proyecto."

    fake = _fake_openai_router(section_fn, intro_text="Intro.")
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        r = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": [
                {"title": "Plan de trabajo", "sort_order": 0},
                {"title": "Equipo", "sort_order": 1},
            ]},
        )
    assert r.status_code == 200
    md = r.json()["markdown"]
    # Único «#» de documento (el del título de la licitación); el resto degradado a ##.
    assert md.count("\n# ") == 0
    assert md.startswith("# Licitación A")
    # El fence que envolvía la sección se eliminó; su contenido se conserva.
    assert "```" not in md
    assert "**Perfiles** del equipo." in md
    # Ambas secciones quedan a nivel 2.
    assert "## Plan de trabajo" in md
    assert "## Equipo" in md


# ── Fase 3: chat de edición del Markdown ──────────────────────────────────────

def test_chat_edits_markdown_and_persists_history(client_a):
    created = _create_memoria(client_a, "# Memoria Técnica\n\nIntro larga.")
    edited = "# Memoria Técnica\n\nVersión editada."
    fake = _fake_openai_json({"markdown": edited, "texto_chat": "He acortado la introducción."})
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        r = client_a.post("/api/v1/licitaciones/lic-a/memoria/chat",
                          json={
                              "doc_id": created["doc_id"],
                              "markdown": "# Memoria Técnica\n\nIntro larga.",
                              "message": "Acorta la intro",
                          })
    assert r.status_code == 200
    data = r.json()
    assert data["markdown"] == edited
    assert data["texto_chat"] == "He acortado la introducción."
    # Documento actualizado.
    saved = client_a.get(
        f"/api/v1/licitaciones/lic-a/memoria/documents/{created['doc_id']}"
    ).json()
    assert saved["markdown"] == edited
    # Historial persistido (user + assistant).
    history = client_a.get(
        f"/api/v1/licitaciones/lic-a/memoria/chat?doc_id={created['doc_id']}"
    ).json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "Acorta la intro"
    assert history[1]["content"] == "He acortado la introducción."


def test_chat_replays_history_into_llm(client_a, db):
    """El segundo turno reinyecta el primero como contexto de conversación."""
    from app.models.domain import MemoriaChatMessage
    created = _create_memoria(client_a)
    db.add_all([
        MemoriaChatMessage(id="m1", licitacion_id="lic-a", user_id="user-a", role="user",
                           doc_id=created["doc_id"], content="Primer mensaje", created_at=_NOW),
        MemoriaChatMessage(id="m2", licitacion_id="lic-a", user_id="user-a", role="assistant",
                           doc_id=created["doc_id"], content="Primera respuesta", created_at=_NOW),
    ])
    db.commit()
    fake = _fake_openai_json({"markdown": "# Doc", "texto_chat": "ok"})
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        client_a.post("/api/v1/licitaciones/lic-a/memoria/chat",
                      json={
                          "doc_id": created["doc_id"],
                          "markdown": "# Doc",
                          "message": "Segundo",
                      })
    sent_messages = fake.chat.completions.create.call_args.kwargs["messages"]
    roles_contents = [(m["role"], m["content"]) for m in sent_messages]
    assert ("user", "Primer mensaje") in roles_contents
    assert ("assistant", "Primera respuesta") in roles_contents


def test_chat_isolation(client_a):
    r = client_a.post("/api/v1/licitaciones/lic-b/memoria/chat",
                      json={"doc_id": "doc-b", "markdown": "x", "message": "y"})
    assert r.status_code == 404


# ── Fase 4: export PDF ─────────────────────────────────────────────────────────

def test_export_returns_pdf(client_a):
    created = _create_memoria(client_a, "# Memoria\n\nTexto.")

    with patch("app.services.memoria_export.render_markdown_pdf", return_value=b"%PDF-1.4 fake"):
        r = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/export",
            json={"doc_id": created["doc_id"]},
        )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_export_uses_body_markdown(client_a):
    with patch("app.services.memoria_export.render_markdown_pdf", return_value=b"%PDF-1.4 x") as mock_render:
        r = client_a.post("/api/v1/licitaciones/lic-a/memoria/export",
                          json={"markdown": "# Del body"})
    assert r.status_code == 200
    assert mock_render.call_args.args == ("# Del body",)
    assert mock_render.call_args.kwargs["variables"]["tender_title"] == "Licitación A"
    assert mock_render.call_args.kwargs["variables"]["document_title"] == ""
    assert mock_render.call_args.kwargs["variables"]["user_email"] == "a@test.com"


def test_export_404_without_document(client_a):
    r = client_a.post("/api/v1/licitaciones/lic-a/memoria/export", json={})
    assert r.status_code == 404


def test_export_503_when_native_libs_missing(client_a):
    with patch("app.services.memoria_export.render_markdown_pdf",
               side_effect=OSError("cannot load library 'libgobject-2.0-0'")):
        r = client_a.post("/api/v1/licitaciones/lic-a/memoria/export",
                          json={"markdown": "# x"})
    assert r.status_code == 503


def test_export_docx_format(client_a):
    """format=docx (5.6): media type de Word, extensión .docx y opciones propagadas."""
    with patch("app.services.memoria_export.render_markdown_docx",
               return_value=b"PK\x03\x04 fake docx") as mock_render:
        r = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/export",
            json={"markdown": "# x", "format": "docx", "include_toc": True,
                  "header_text": "ACME S.L.", "footer_text": "Oferta"},
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert 'filename="memoria_lic-a.docx"' in r.headers["content-disposition"]
    options = mock_render.call_args.kwargs["options"]
    assert options.include_toc is True
    assert options.header_text == "ACME S.L."
    assert options.footer_text == "Oferta"


def test_export_invalid_format_rejected(client_a):
    r = client_a.post("/api/v1/licitaciones/lic-a/memoria/export",
                      json={"markdown": "# x", "format": "odt"})
    assert r.status_code == 422


# ── Documento ──────────────────────────────────────────────────────────────────

def test_manual_save_updates_document(client_a):
    fake = _fake_openai_text("# Memoria\n\nVersión inicial.")
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        created = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": []},
        ).json()

    saved = client_a.patch(
        f"/api/v1/licitaciones/lic-a/memoria/documents/{created['doc_id']}",
        json={"title": "Versión revisada", "markdown": "# Memoria\n\nCambios manuales."},
    )

    assert saved.status_code == 200
    assert saved.json()["title"] == "Versión revisada"
    assert saved.json()["markdown"] == "# Memoria\n\nCambios manuales."

    fetched = client_a.get(
        f"/api/v1/licitaciones/lic-a/memoria/documents/{created['doc_id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["markdown"] == "# Memoria\n\nCambios manuales."


def test_documents_keep_independent_versions(client_a):
    fake = _fake_openai_text("# Memoria\n\nContenido.")
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        first = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": []},
        ).json()
        second = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": []},
        ).json()

    documents = client_a.get("/api/v1/licitaciones/lic-a/memoria/documents")
    assert documents.status_code == 200
    assert {doc["id"] for doc in documents.json()} == {
        first["doc_id"],
        second["doc_id"],
    }


def test_export_uses_last_saved_document(client_a):
    fake = _fake_openai_text("# Memoria\n\nVersión inicial.")
    with patch("app.services.memoria.get_openai_client", return_value=fake), \
         patch("app.services.memoria.hybrid_search", new=AsyncMock(return_value=[])):
        created = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/propuesta",
            json={"esquema": []},
        ).json()

    latest_markdown = "# Memoria\n\nÚltima edición guardada."
    client_a.patch(
        f"/api/v1/licitaciones/lic-a/memoria/documents/{created['doc_id']}",
        json={"markdown": latest_markdown},
    )

    with patch(
        "app.services.memoria_export.render_markdown_pdf",
        return_value=b"%PDF-1.4 saved",
    ) as render:
        exported = client_a.post(
            "/api/v1/licitaciones/lic-a/memoria/export",
            json={"doc_id": created["doc_id"]},
        )

    assert exported.status_code == 200
    assert render.call_args.args == (latest_markdown,)
    assert render.call_args.kwargs["variables"]["document_title"]


def test_get_documents_empty(client_a):
    r = client_a.get("/api/v1/licitaciones/lic-a/memoria/documents")
    assert r.status_code == 200
    assert r.json() == []


# ── CRUD de secciones (esquema persistido) ────────────────────────────────────

def test_save_and_list_sections_ordered(client_a):
    payload = {"sections": [
        {"title": "Metodología", "sort_order": 1, "max_puntos": 30},
        {"title": "Introducción", "sort_order": 0},
    ]}
    r = client_a.post("/api/v1/licitaciones/lic-a/memoria/sections", json=payload)
    assert r.status_code == 201
    assert [s["title"] for s in r.json()] == ["Introducción", "Metodología"]
    r2 = client_a.get("/api/v1/licitaciones/lic-a/memoria/sections")
    assert [s["title"] for s in r2.json()] == ["Introducción", "Metodología"]


def test_patch_section(client_a, db):
    db.add(_section("sec-1", "lic-a", "user-a", "Original", order=0))
    db.commit()
    r = client_a.patch("/api/v1/licitaciones/lic-a/memoria/sections/sec-1",
                       json={"title": "Editada", "max_puntos": 40})
    assert r.status_code == 200
    assert r.json()["title"] == "Editada"
    assert r.json()["status"] == "edited"


def test_delete_section(client_a, db):
    db.add(_section("sec-1", "lic-a", "user-a", "Borrar", order=0))
    db.commit()
    r = client_a.delete("/api/v1/licitaciones/lic-a/memoria/sections/sec-1")
    assert r.status_code == 204
    assert client_a.get("/api/v1/licitaciones/lic-a/memoria/sections").json() == []


def test_delete_nonexistent_returns_404(client_a):
    r = client_a.delete("/api/v1/licitaciones/lic-a/memoria/sections/nope")
    assert r.status_code == 404


# ── Aislamiento (§10) ─────────────────────────────────────────────────────────

def test_isolation_cannot_list_other_users_licitacion(client_a):
    r = client_a.get("/api/v1/licitaciones/lic-b/memoria/sections")
    assert r.status_code == 404


def test_isolation_cannot_patch_other_users_section(client_a, db):
    db.add(_section("sec-b", "lic-b", "user-b", "De B", order=0))
    db.commit()
    r = client_a.patch("/api/v1/licitaciones/lic-b/memoria/sections/sec-b",
                       json={"title": "Hackeada"})
    assert r.status_code == 404


def test_isolation_cannot_delete_other_users_section(client_a, db):
    db.add(_section("sec-b", "lic-b", "user-b", "De B", order=0))
    db.commit()
    r = client_a.delete("/api/v1/licitaciones/lic-b/memoria/sections/sec-b")
    assert r.status_code == 404


# ── Coherencia (spec-MP §4) ─────────────────────────────────────────────

def test_coherencia_returns_issue_list(client_a):
    created = _create_memoria(client_a)
    client_a.patch(
        f"/api/v1/licitaciones/lic-a/memoria/documents/{created['doc_id']}",
        json={"markdown": "# Memoria\n\n## Plan\n\n[COMPLETAR: cifra]."},
    )
    fake = _fake_openai_json({"incidencias": [
        {"tipo": "completar_pendiente", "apartado": "Plan", "detalle": "[COMPLETAR: cifra]"},
        {"tipo": "verificar", "apartado": "Plan", "detalle": "Afirmación sin respaldo"},
        {"malformada": True},
    ]})
    with patch("app.services.memoria.get_openai_client", return_value=fake):
        r = client_a.post(
            f"/api/v1/licitaciones/lic-a/memoria/documents/{created['doc_id']}/coherencia"
        )
    assert r.status_code == 200
    data = r.json()
    assert data["doc_id"] == created["doc_id"]
    # Las entradas malformadas se descartan; el resto conserva tipo/apartado/detalle.
    assert [i["tipo"] for i in data["incidencias"]] == ["completar_pendiente", "verificar"]
    # El borrador viaja al LLM fenceado como datos (<borrador>).
    sent = fake.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert sent.startswith("<borrador>")
    assert "[COMPLETAR: cifra]" in sent


def test_coherencia_404_for_missing_document(client_a):
    r = client_a.post("/api/v1/licitaciones/lic-a/memoria/documents/nope/coherencia")
    assert r.status_code == 404
