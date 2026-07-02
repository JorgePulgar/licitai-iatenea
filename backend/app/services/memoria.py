"""
Servicio de la Memoria Técnica (flujo completo, ADR-002).

Tres fases:
  1. ESQUEMA   (`propose_esquema`)   → estructura de secciones en JSON, grounded en
     los criterios de adjudicación (PliegoRequirement, fallback PCAP), con plantilla
     per-usuario (agregación SQL) y secciones existentes como contexto.
  2. PROPUESTA (`generate_propuesta`)→ redacta el Markdown desde el esquema aprobado,
     grounded en los fragmentos del PPT + el perfil de empresa.
  3. CHAT      (`edit_propuesta_chat`)→ edita el Markdown con histórico de conversación
     y guardrail anti-drift; persiste documento e histórico.

El esquema vive en `memoria_sections`; el Markdown en `memoria_documents`; el chat en
`memoria_chat_messages`. Clave de sesión: licitacion_id + user_id (sin session_id).
"""

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.domain import (
    CompanyProfile,
    MemoriaChatMessage,
    MemoriaDocument,
    MemoriaSection,
    PliegoRequirement,
)
from app.models.schemas import (
    MemoriaEsquemaResponse,
    MemoriaSectionDraft,
    MemoriaSectionResponse,
)
from app.prompts.memoria import (
    MEMORIA_CHAT_PROMPT,
    MEMORIA_ESQUEMA_PROMPT,
    MEMORIA_INTRO_PROMPT,
    MEMORIA_SECTION_PROMPT,
)
from app.services.embeddings import get_openai_client
from app.services.match import _build_profile_text
from app.services.query import hybrid_search
from app.services.templates import (
    build_templates_context,
    get_templates_by_ids,
)

logger = get_logger(__name__)

LLM_MODEL = "extraccion_datos_4o"
LLM_TEMPERATURE = 0.2          # extracción / edición (determinista)
PROPUESTA_TEMPERATURE = 0.5    # redacción inicial (algo creativa, ADR-002 §4)

# Cuántas secciones de plantilla (por frecuencia) se pasan al LLM como base.
TEMPLATE_TOP_N = 12
# Cuántos chunks recupera el fallback de grounding del esquema (criterios PCAP).
GROUNDING_TOP_K = 8
# Cuántos chunks del PPT se recuperan para fundamentar la redacción de la propuesta.
PPT_CONTEXT_TOP_K = 20

# ── Redacción multi-agente (fan-out, ADR-002 §4) ────────────────────────────
INTRO_TEMPERATURE = 0.3            # introducción: hila, no inventa (baja temperatura)
INTRO_MAX_TOKENS = 400             # la intro es corta (2-4 frases); acota coste y output
# Máximo de agentes de sección en vuelo a la vez (guarda de cuota TPM/RPM de Azure).
SECTION_CONCURRENCY = 5
# Chunks del PPT que recupera cada agente de sección (retrieval específico).
SECTION_PPT_TOP_K = 8
# Máximo de requisitos relevantes que se inyectan a cada agente de sección.
SECTION_REQUISITOS_TOP_N = 6
# Marcador para una sección que el LLM no pudo generar (degradación, no se aborta).
SECTION_FAILURE_MARKER = "_[COMPLETAR: sección no generada — reintenta la propuesta]_"


# ── Lectura / serialización ─────────────────────────────────────────────────

def _to_response(section: MemoriaSection) -> MemoriaSectionResponse:
    return MemoriaSectionResponse.model_validate(section)


def get_sections(licitacion_id: str, user_id: str, db: Session) -> list[MemoriaSectionResponse]:
    """Secciones existentes de la licitación, ordenadas por `orden`."""
    rows = (
        db.query(MemoriaSection)
        .filter(
            MemoriaSection.licitacion_id == licitacion_id,
            MemoriaSection.user_id == user_id,
        )
        .order_by(MemoriaSection.sort_order.asc())
        .all()
    )
    return [_to_response(r) for r in rows]


def get_chat_history(
    licitacion_id: str,
    user_id: str,
    db: Session,
    doc_id: str | None = None,
) -> list[MemoriaChatMessage]:
    """Historial del chat de propuesta, en orden cronológico. Si se pasa ``doc_id``
    se filtra por documento (cada versión de la Memoria mantiene su propio hilo)."""
    q = db.query(MemoriaChatMessage).filter(
        MemoriaChatMessage.licitacion_id == licitacion_id,
        MemoriaChatMessage.user_id == user_id,
    )
    if doc_id is not None:
        q = q.filter(MemoriaChatMessage.doc_id == doc_id)
    return q.order_by(MemoriaChatMessage.created_at.asc()).all()


# ── Plantilla (rama 2): agregación per-usuario ──────────────────────────────

def derive_template(user_id: str, exclude_licitacion_id: str, db: Session) -> list[str]:
    """
    Títulos de sección recurrentes en las memorias `accepted` del propio usuario,
    excluyendo la licitación actual. Rankeados por frecuencia. Agregación SQL,
    respeta el aislamiento §10 (solo secciones del propio user_id).
    """
    normalized = func.lower(func.trim(MemoriaSection.title))
    rows = (
        db.query(MemoriaSection.title, func.count().label("freq"))
        .filter(
            MemoriaSection.user_id == user_id,
            MemoriaSection.licitacion_id != exclude_licitacion_id,
            MemoriaSection.status == "accepted",
        )
        .group_by(normalized, MemoriaSection.title)
        .order_by(func.count().desc())
        .limit(TEMPLATE_TOP_N)
        .all()
    )
    # Deduplica por título normalizado preservando el orden por frecuencia.
    seen: set[str] = set()
    titles: list[str] = []
    for title, _freq in rows:
        key = " ".join((title or "").lower().split())
        if key and key not in seen:
            seen.add(key)
            titles.append(title)
    return titles


# ── Grounding (rama 3): criterios de adjudicación ───────────────────────────

async def _get_criterios_text(licitacion_id: str, user_id: str, db: Session) -> str:
    """
    Texto de los criterios de adjudicación para fundamentar la propuesta.
    Reutiliza `PliegoRequirement` (categoria='criterio_adjudicacion') ya extraídos;
    si no existen, cae a `hybrid_search` sobre el PCAP (DRY §6).
    """
    criterios = (
        db.query(PliegoRequirement)
        .filter(
            PliegoRequirement.licitacion_id == licitacion_id,
            PliegoRequirement.categoria == "criterio_adjudicacion",
        )
        .all()
    )
    if criterios:
        lines = []
        for c in criterios:
            page = f" [p. {c.pagina}]" if c.pagina else ""
            lines.append(f"- {c.descripcion}{page}")
        return "\n".join(lines)

    # Fallback: buscar en el PCAP los criterios de juicio de valor.
    chunks = await hybrid_search(
        "criterios de adjudicación, juicio de valor, puntuación máxima de la memoria técnica",
        licitacion_id,
        user_id,
        top_k=GROUNDING_TOP_K,
        document_type="pcap",
    )
    if not chunks:
        return ""
    return "\n\n".join(
        f"[p. {c.get('page_number', '?')}] {c['text']}" for c in chunks
    )


# ── Propuesta (chat) ─────────────────────────────────────────────────────────

def _build_user_message(
    title: str,
    user_message: str,
    criterios_text: str,
    template_titles: list[str],
    existing: list[MemoriaSectionResponse],
    templates_context: str = "",
) -> str:
    parts = [f"Licitación: '{title}'", f"\nMensaje del usuario: {user_message}"]

    if criterios_text:
        parts.append(f"\nCRITERIOS DE ADJUDICACIÓN del pliego:\n{criterios_text}")
    else:
        parts.append(
            "\nCRITERIOS DE ADJUDICACIÓN: no disponibles. Si te faltan datos, "
            "pregunta al usuario en 'reply'."
        )

    if template_titles:
        joined = "\n".join(f"- {t}" for t in template_titles)
        parts.append(f"\nPLANTILLA (secciones de memorias previas del usuario):\n{joined}")

    if templates_context:
        parts.append(f"\n{templates_context}")

    if existing:
        joined = "\n".join(f"- {s.title}" for s in existing)
        parts.append(f"\nSECCIONES EXISTENTES (refínalas, no las dupliques):\n{joined}")

    return "\n".join(parts)


def _parse_sections(raw_sections: list[dict[str, Any]]) -> list[MemoriaSectionDraft]:
    drafts: list[MemoriaSectionDraft] = []
    for i, s in enumerate(raw_sections):
        title = (s.get("title") or "").strip()
        if not title:
            continue
        drafts.append(
            MemoriaSectionDraft(
                title=title,
                description=s.get("description"),
                criterio_adjudicacion=s.get("criterio_adjudicacion"),
                max_puntos=s.get("max_puntos"),
                page_budget=s.get("page_budget"),
                sort_order=s.get("sort_order", i),
            )
        )
    return drafts


async def propose_esquema(
    licitacion_id: str,
    user_id: str,
    title: str,
    user_message: str,
    db: Session,
    template_ids: list[str] | None = None,
) -> MemoriaEsquemaResponse:
    """
    Propone (sin persistir) la estructura de secciones vía LLM, combinando criterios
    del pliego (grounding), plantilla del usuario, secciones existentes y, si se pasan
    ``template_ids``, plantillas de referencia subidas por la empresa (CompanyTemplate).
    El chat de refinado opera sobre el Markdown (fase 3); el esquema no persiste turnos.
    """
    t_start = time.monotonic()

    existing = get_sections(licitacion_id, user_id, db)
    template_titles = derive_template(user_id, licitacion_id, db)
    criterios_text = await _get_criterios_text(licitacion_id, user_id, db)

    company_templates = (
        get_templates_by_ids(template_ids or [], user_id, db) if template_ids else []
    )
    templates_context = build_templates_context(company_templates)

    branch = (
        "existing" if existing
        else "template" if template_titles
        else "grounded" if criterios_text
        else "ask_user"
    )
    logger.info(
        "Memoria propose started",
        extra={
            "licitacion_id": licitacion_id,
            "branch": branch,
            "has_criterios": bool(criterios_text),
            "template_count": len(template_titles),
            "existing_count": len(existing),
            "company_templates_count": len(company_templates),
        },
    )

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI not configured — memoria esquema unavailable.")
        return MemoriaEsquemaResponse(
            reply="El servicio de propuesta de secciones no está disponible en este momento.",
            esquema=[],
        )

    llm_user_message = _build_user_message(
        title, user_message, criterios_text, template_titles, existing, templates_context
    )

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": MEMORIA_ESQUEMA_PROMPT},
                {"role": "user", "content": llm_user_message},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON for memoria esquema of licitacion {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error proposing memoria esquema for licitacion {licitacion_id}: {e}", exc_info=True)
        raise

    reply = (data.get("reply") or "").strip() or "He propuesto una estructura de secciones."
    esquema = _parse_sections(data.get("secciones", []))

    latency_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "Memoria esquema completed",
        extra={
            "licitacion_id": licitacion_id,
            "branch": branch,
            "esquema_count": len(esquema),
            "latency_ms": latency_ms,
            "model": LLM_MODEL,
        },
    )

    return MemoriaEsquemaResponse(reply=reply, esquema=esquema)


def _persist_chat_turn(
    licitacion_id: str,
    user_id: str,
    doc_id: str,
    user_message: str,
    assistant_reply: str,
    db: Session,
    session_factory: Callable[[], Session] | None,
) -> None:
    """
    Persiste el turno (usuario + asistente). Usa una sesión fresca si se pasa
    ``session_factory`` (la del request puede tener una conexión TCP rancia tras
    el LLM); en caso contrario reutiliza ``db`` y no la cierra.
    """
    now = datetime.now(timezone.utc)
    write_db = session_factory() if session_factory else db
    try:
        write_db.add(
            MemoriaChatMessage(
                id=str(uuid.uuid4()),
                licitacion_id=licitacion_id,
                user_id=user_id,
                doc_id=doc_id,
                role="user",
                content=user_message,
                created_at=now,
            )
        )
        write_db.add(
            MemoriaChatMessage(
                id=str(uuid.uuid4()),
                licitacion_id=licitacion_id,
                user_id=user_id,
                doc_id=doc_id,
                role="assistant",
                content=assistant_reply,
                # +1ms para garantizar orden cronológico user→assistant
                created_at=datetime.now(timezone.utc),
            )
        )
        write_db.commit()
    except Exception:
        write_db.rollback()
        logger.warning(f"Failed to persist memoria chat turn for licitacion {licitacion_id}", exc_info=True)
    finally:
        # Solo cerramos si abrimos una sesión propia (no la del request).
        if write_db is not db:
            write_db.close()


# ── Grounding de la redacción (PPT + perfil de empresa) ─────────────────────

async def _get_ppt_context(licitacion_id: str, user_id: str) -> str:
    """Fragmentos del PPT que fundamentan la redacción (qué exige el pliego)."""
    chunks = await hybrid_search(
        "objeto del contrato, prestaciones, requisitos técnicos, alcance del servicio, "
        "entregables, niveles de servicio y plazos de ejecución",
        licitacion_id,
        user_id,
        top_k=PPT_CONTEXT_TOP_K,
        document_type="ppt",
    )
    if not chunks:
        return ""
    chunks.sort(key=lambda c: c.get("page_number") or 0)
    return "\n\n".join(
        f"[p. {c.get('page_number', '?')}] {c['text']}" for c in chunks
    )


def _get_profile_text(user_id: str, db: Session) -> str:
    """Perfil de empresa por defecto del usuario (qué ofrece). Reutiliza match._build_profile_text."""
    profile = (
        db.query(CompanyProfile)
        .filter(CompanyProfile.created_by == user_id, CompanyProfile.is_default == True)  # noqa: E712
        .first()
    )
    if not profile:
        return "No hay perfil de empresa configurado."
    return _build_profile_text(profile)


# ── Documento Markdown (persistencia) ────────────────────────────────────────

def get_documents(licitacion_id: str, user_id: str, db: Session) -> list[MemoriaDocument]:
    return (
        db.query(MemoriaDocument)
        .filter(
            MemoriaDocument.licitacion_id == licitacion_id,
            MemoriaDocument.user_id == user_id,
        )
        .order_by(MemoriaDocument.updated_at.desc())
        .all()
    )

def get_document_by_id(doc_id: str, licitacion_id: str, user_id: str, db: Session) -> MemoriaDocument | None:
    return (
        db.query(MemoriaDocument)
        .filter(
            MemoriaDocument.id == doc_id,
            MemoriaDocument.licitacion_id == licitacion_id,
            MemoriaDocument.user_id == user_id,
        )
        .first()
    )


def create_document(
    licitacion_id: str,
    user_id: str,
    title: str,
    markdown: str,
    db: Session,
    session_factory: Callable[[], Session] | None,
) -> MemoriaDocument:
    """Crea un nuevo documento de Memoria."""
    now = datetime.now(timezone.utc)
    write_db = session_factory() if session_factory else db
    try:
        doc = MemoriaDocument(
            id=str(uuid.uuid4()),
            licitacion_id=licitacion_id,
            user_id=user_id,
            title=title,
            markdown=markdown,
            created_at=now,
            updated_at=now,
        )
        write_db.add(doc)
        write_db.commit()
        write_db.refresh(doc)
        return doc
    except Exception:
        write_db.rollback()
        raise
    finally:
        if write_db is not db:
            write_db.close()

def update_document(
    doc_id: str,
    licitacion_id: str,
    user_id: str,
    title: str | None,
    markdown: str | None,
    db: Session,
    session_factory: Callable[[], Session] | None,
) -> MemoriaDocument | None:
    """Actualiza un documento existente."""
    now = datetime.now(timezone.utc)
    write_db = session_factory() if session_factory else db
    try:
        doc = (
            write_db.query(MemoriaDocument)
            .filter(
                MemoriaDocument.id == doc_id,
                MemoriaDocument.licitacion_id == licitacion_id,
                MemoriaDocument.user_id == user_id,
            )
            .first()
        )
        if not doc:
            return None
        
        if title is not None:
            doc.title = title
        if markdown is not None:
            doc.markdown = markdown
        doc.updated_at = now
        
        write_db.commit()
        write_db.refresh(doc)
        return doc
    except Exception:
        write_db.rollback()
        raise
    finally:
        if write_db is not db:
            write_db.close()


# ── Fase 2: redacción de la propuesta (multi-agente, fan-out) ───────────────
# Un agente por sección redacta su Markdown en paralelo (grounded en evidencia y
# requisitos específicos de la sección); el cosido del documento final es determinista
# en código (el LLM solo redacta la introducción), para que no pueda truncarse.

# Palabras vacías que no aportan a la relevancia léxica sección↔requisito.
_STOPWORDS = {
    "de", "la", "el", "los", "las", "un", "una", "y", "o", "a", "en", "del", "al",
    "que", "con", "por", "para", "su", "sus", "se", "lo", "es", "como", "más",
}


def _tokens(text: str) -> set[str]:
    """Tokens normalizados (minúsculas, sin stopwords ni tokens de <3 chars)."""
    words = re.findall(r"[a-záéíóúñü0-9]+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _load_requisitos(licitacion_id: str, db: Session) -> list[PliegoRequirement]:
    """Todos los requisitos extraídos del pliego (se cargan una vez y se reparten)."""
    return (
        db.query(PliegoRequirement)
        .filter(PliegoRequirement.licitacion_id == licitacion_id)
        .all()
    )


def _select_requisitos_for_section(
    section: MemoriaSectionDraft,
    requisitos: list[PliegoRequirement],
) -> str:
    """
    Requisitos más relevantes para la sección, por solapamiento léxico con su título,
    descripción y criterio. Evita N consultas a BD y no vuelca todos los requisitos en
    cada agente. Devuelve texto formateado (o "" si no hay).
    """
    if not requisitos:
        return ""
    section_tokens = _tokens(
        " ".join(filter(None, [section.title, section.description, section.criterio_adjudicacion]))
    )
    if not section_tokens:
        return ""

    scored: list[tuple[int, PliegoRequirement]] = []
    for r in requisitos:
        overlap = len(section_tokens & _tokens(r.descripcion))
        if overlap > 0:
            scored.append((overlap, r))
    scored.sort(key=lambda x: x[0], reverse=True)

    lines = []
    for _score, r in scored[:SECTION_REQUISITOS_TOP_N]:
        page = f" [p. {r.pagina}]" if r.pagina else ""
        flag = "" if r.es_obligatorio else " (deseable)"
        lines.append(f"- {r.descripcion}{page}{flag}")
    return "\n".join(lines)


async def _get_section_evidence(licitacion_id: str, user_id: str, section: MemoriaSectionDraft) -> str:
    """Fragmentos del PPT específicos de la sección (query = título + descripción + criterio)."""
    query = " ".join(
        filter(None, [section.title, section.description, section.criterio_adjudicacion])
    ) or section.title
    chunks = await hybrid_search(
        query,
        licitacion_id,
        user_id,
        top_k=SECTION_PPT_TOP_K,
        document_type="ppt",
    )
    if not chunks:
        return ""
    chunks.sort(key=lambda c: c.get("page_number") or 0)
    return "\n\n".join(f"[p. {c.get('page_number', '?')}] {c['text']}" for c in chunks)


async def _generate_section(
    client: Any,
    licitacion_id: str,
    user_id: str,
    title: str,
    section: MemoriaSectionDraft,
    requisitos: list[PliegoRequirement],
    profile_text: str,
    templates_context: str,
    semaphore: asyncio.Semaphore,
) -> str:
    """
    Redacta el Markdown de UNA sección, grounded en evidencia del PPT + requisitos
    propios. Degrada (devuelve la sección con un marcador) si el LLM falla, para no
    abortar toda la propuesta (§8: siempre producir un documento trazable).
    """
    async with semaphore:
        evidence = await _get_section_evidence(licitacion_id, user_id, section)
        requisitos_text = _select_requisitos_for_section(section, requisitos)

        meta = [f"Título de la sección: {section.title}"]
        if section.description:
            meta.append(f"Qué debe cubrir: {section.description}")
        if section.criterio_adjudicacion:
            meta.append(f"Criterio de adjudicación al que responde: {section.criterio_adjudicacion}")
        if section.max_puntos is not None:
            meta.append(f"Puntos del criterio: {section.max_puntos}")
        if section.page_budget is not None:
            meta.append(f"Extensión recomendada: {section.page_budget} páginas")

        parts = [
            f"Licitación: '{title}'",
            "\nSECCIÓN A REDACTAR:\n" + "\n".join(meta),
            f"\nEVIDENCIA DEL PPT (relevante para esta sección):\n{evidence or 'No disponible.'}",
            f"\nREQUISITOS RELEVANTES:\n{requisitos_text or 'No disponibles.'}",
            f"\nPERFIL DE LA EMPRESA:\n{profile_text}",
        ]
        if templates_context:
            parts.append(f"\n{templates_context}")
        user_message = "\n".join(parts)

        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                temperature=PROPUESTA_TEMPERATURE,
                messages=[
                    {"role": "system", "content": MEMORIA_SECTION_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            markdown = (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(
                f"Section agent failed for '{section.title}' (licitacion {licitacion_id}): {e}",
                exc_info=True,
            )
            markdown = ""

        if not markdown:
            return f"## {section.title}\n\n{SECTION_FAILURE_MARKER}"
        return markdown


async def _generate_intro(client: Any, title: str, section_titles: list[str]) -> str:
    """
    Redacta SOLO la introducción global (2-4 frases) a partir de los títulos de sección.
    No re-emite el contenido de las secciones (eso lo cose el código), por lo que el LLM
    no puede truncar el documento. Devuelve "" si falla (la intro es opcional).
    """
    if not section_titles:
        return ""
    titles_block = "\n".join(f"- {t}" for t in section_titles)
    user_message = (
        f"Título de la licitación: '{title}'\n\n"
        f"SECCIONES DE LA MEMORIA (en orden):\n{titles_block}"
    )
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=INTRO_TEMPERATURE,
            max_tokens=INTRO_MAX_TOKENS,
            messages=[
                {"role": "system", "content": MEMORIA_INTRO_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"Intro agent failed for licitacion (title '{title}'): {e}", exc_info=True)
        return ""


# Encabezado de nivel 2 al inicio de una sección (con espacios opcionales tras ##).
_H2_PREFIX = re.compile(r"^\s{0,3}##\s")
# Línea que abre/cierra un bloque de código; captura el lenguaje (info string).
_FENCE_LINE = re.compile(r"^[ \t]*(?:```|~~~)[ \t]*([A-Za-z0-9_+-]*)[ \t]*$")
# Encabezado de nivel 1 al inicio de línea (no «##»): lo degradamos a nivel 2.
_H1_LINE = re.compile(r"^# (?=\S)", re.MULTILINE)


def _strip_stray_fences(md: str) -> str:
    """
    Elimina los "fences" que el agente generó por error envolviendo prosa Markdown
    (```markdown … ``` o ``` … ```), incluso si quedaron sin cerrar: marked los pinta
    como bloque de código y deja el `##`/`**` sin interpretar. Conserva los bloques con
    lenguaje real (```python, …): una Memoria Técnica no contiene código, así que solo
    desenvolvemos fences sin lenguaje o etiquetados markdown/md (siempre un error).
    """
    out: list[str] = []
    in_stray = False   # fence de prosa mal generado → se descarta la línea de fence
    in_code = False    # fence con lenguaje real → se conserva intacto
    for line in md.split("\n"):
        m = _FENCE_LINE.match(line)
        if m:
            info = m.group(1).lower()
            if in_code:
                out.append(line); in_code = False; continue
            if in_stray:
                in_stray = False; continue
            if info in ("", "markdown", "md"):
                in_stray = True; continue
            out.append(line); in_code = True; continue
        out.append(line)
    return "\n".join(out)


def _normalize_section(markdown: str, fallback_title: str) -> str:
    """
    Normaliza el Markdown de una sección para que TODAS tengan el mismo estilo y se
    rendericen bien tras el cosido determinista:
      1. Desenvuelve los fences espurios que el agente pusiera (si no, marked los pinta
         como código monoespaciado en vez de texto).
      2. Degrada encabezados de nivel 1 (#) a nivel 2 (##): el «#» del documento lo pone
         el código, y mezclar niveles rompe la jerarquía.
      3. Garantiza que empiece por «## <título>» (si el agente no lo puso).
    """
    md = (markdown or "").strip()
    if not md:
        return f"## {fallback_title}"

    md = _strip_stray_fences(md).strip()
    md = _H1_LINE.sub("## ", md)

    if not _H2_PREFIX.match(md):
        md = f"## {fallback_title}\n\n{md}"
    return md


def _stitch_memoria(title: str, intro: str, sections: list[tuple[str, str]]) -> str:
    """
    Cose el documento final de forma DETERMINISTA: «# título», introducción opcional y
    las secciones en orden, normalizadas. El contenido de las secciones se preserva
    verbatim (el código no lo reescribe), eliminando el truncamiento del LLM.

    ``sections`` es una lista de (título_fallback, markdown) en el orden final.
    """
    parts = [f"# {title}"]
    if intro:
        parts.append(intro)
    for fallback_title, md in sections:
        parts.append(_normalize_section(md, fallback_title))
    return "\n\n".join(parts)


async def generate_propuesta(
    licitacion_id: str,
    user_id: str,
    title: str,
    esquema: list[MemoriaSectionDraft],
    db: Session,
    session_factory: Callable[[], Session] | None = None,
    template_ids: list[str] | None = None,
) -> MemoriaDocument:
    """
    Redacta la Memoria Técnica con un esquema multi-agente (fan-out): un agente redacta
    cada sección en paralelo (grounded en evidencia del PPT + requisitos propios de la
    sección + perfil). El documento final se cose de forma DETERMINISTA en código
    (secciones verbatim); el LLM solo redacta la introducción global, evitando el
    truncamiento del antiguo ensamblador. Persiste en `memoria_documents`. Si se pasan
    ``template_ids``, inyecta el estilo de las plantillas.
    """
    t_start = time.monotonic()

    profile_text = _get_profile_text(user_id, db)
    requisitos = _load_requisitos(licitacion_id, db)
    company_templates = (
        get_templates_by_ids(template_ids or [], user_id, db) if template_ids else []
    )
    templates_context = build_templates_context(company_templates)

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI not configured — memoria propuesta unavailable.")
        markdown = "# Memoria Técnica\n\n_El servicio de redacción no está disponible en este momento._"
        return create_document(licitacion_id, user_id, "Borrador de Memoria", markdown, db, session_factory)

    ordered = sorted(esquema, key=lambda s: s.sort_order if s.sort_order is not None else 0)

    # Fan-out: un agente por sección, en paralelo (acotado por semáforo).
    semaphore = asyncio.Semaphore(SECTION_CONCURRENCY)
    section_markdowns = await asyncio.gather(
        *(
            _generate_section(
                client, licitacion_id, user_id, title, section,
                requisitos, profile_text, templates_context, semaphore,
            )
            for section in ordered
        )
    )

    failed = sum(1 for md in section_markdowns if SECTION_FAILURE_MARKER in md)
    if ordered and failed == len(ordered):
        # Todas las secciones fallaron: no degradamos a un documento vacío, abortamos.
        raise RuntimeError(
            f"All {failed} section agents failed for licitacion {licitacion_id}; aborting propuesta."
        )

    # Ensamblado DETERMINISTA: el código cose las secciones (preservadas verbatim) y el
    # LLM solo redacta la introducción global; así el documento no puede truncarse.
    intro = await _generate_intro(client, title, [s.title for s in ordered])
    markdown = _stitch_memoria(
        title,
        intro,
        [(s.title, md) for s, md in zip(ordered, section_markdowns)],
    )

    doc = create_document(licitacion_id, user_id, "Borrador de Memoria", markdown, db, session_factory)

    logger.info(
        "Memoria propuesta generated",
        extra={
            "licitacion_id": licitacion_id,
            "doc_id": doc.id,
            "sections": len(ordered),
            "sections_failed": failed,
            "requisitos_count": len(requisitos),
            "company_templates_count": len(company_templates),
            "markdown_len": len(markdown),
            "concurrency": SECTION_CONCURRENCY,
            "latency_ms": int((time.monotonic() - t_start) * 1000),
            "model": LLM_MODEL,
        },
    )
    return doc


# ── Fase 3: chat de refinado sobre el Markdown ──────────────────────────────

CHAT_HISTORY_TURNS = 20  # cuántos mensajes previos se reinyectan al LLM


async def edit_propuesta_chat(
    doc_id: str,
    licitacion_id: str,
    user_id: str,
    title: str,
    markdown: str,
    message: str,
    db: Session,
    session_factory: Callable[[], Session] | None = None,
) -> tuple[str, str]:
    """
    Edita el Markdown según la petición del usuario, con histórico de conversación y
    grounding (PPT + perfil). Persiste documento e histórico. Devuelve (markdown, texto_chat).
    """
    t_start = time.monotonic()

    # Histórico previo del MISMO documento (cada versión tiene su propio hilo).
    history = get_chat_history(licitacion_id, user_id, db, doc_id=doc_id)[-CHAT_HISTORY_TURNS:]
    ppt_context = await _get_ppt_context(licitacion_id, user_id)
    profile_text = _get_profile_text(user_id, db)

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI not configured — memoria chat unavailable.")
        return markdown, "El servicio de edición no está disponible en este momento."

    messages: list[dict[str, str]] = [{"role": "system", "content": MEMORIA_CHAT_PROMPT}]
    for m in history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({
        "role": "user",
        "content": (
            f"DOCUMENTO ACTUAL (Markdown):\n{markdown}\n\n"
            f"FRAGMENTOS DEL PPT:\n{ppt_context or 'No disponibles.'}\n\n"
            f"PERFIL DE LA EMPRESA:\n{profile_text}\n\n"
            f"PETICIÓN DEL USUARIO: {message}\n\n"
            f"RECORDATORIO CRÍTICO: SOLO debes modificar lo que pide el usuario. "
            f"El resto del documento debe permanecer EXACTAMENTE igual, carácter por carácter. "
            f"No arregles estilo ni modifiques otras partes."
        ),
    })

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=messages,
        )
        data = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON for memoria chat of licitacion {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error editing propuesta for licitacion {licitacion_id}: {e}", exc_info=True)
        raise

    new_markdown = (data.get("markdown") or markdown).strip() or markdown
    texto_chat = (data.get("texto_chat") or "").strip() or "Hecho."

    # Persiste el turno de chat y el documento editado (sesiones frescas tras el LLM).
    _persist_chat_turn(licitacion_id, user_id, doc_id, message, texto_chat, db, session_factory)
    update_document(doc_id, licitacion_id, user_id, None, new_markdown, db, session_factory)

    logger.info(
        "Memoria chat edit completed",
        extra={
            "licitacion_id": licitacion_id,
            "history_turns": len(history),
            "markdown_len": len(new_markdown),
            "latency_ms": int((time.monotonic() - t_start) * 1000),
            "model": LLM_MODEL,
        },
    )
    return new_markdown, texto_chat


# ── Persistencia de secciones (aceptar / editar / borrar) ───────────────────

def save_sections(
    licitacion_id: str,
    user_id: str,
    drafts: list[MemoriaSectionDraft],
    db: Session,
) -> list[MemoriaSectionResponse]:
    """
    Reemplaza el esqueleto de la licitación por las secciones aceptadas.
    Borra las previas y persiste las nuevas con status='accepted'.
    """
    db.query(MemoriaSection).filter(
        MemoriaSection.licitacion_id == licitacion_id,
        MemoriaSection.user_id == user_id,
    ).delete()

    now = datetime.now(timezone.utc)
    rows: list[MemoriaSection] = []
    for i, d in enumerate(drafts):
        row = MemoriaSection(
            id=str(uuid.uuid4()),
            licitacion_id=licitacion_id,
            user_id=user_id,
            title=d.title,
            description=d.description,
            criterio_adjudicacion=d.criterio_adjudicacion,
            max_puntos=d.max_puntos,
            page_budget=d.page_budget,
            sort_order=d.sort_order if d.sort_order is not None else i,
            status="accepted",
            source="user",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        rows.append(row)
    db.commit()

    rows.sort(key=lambda r: r.sort_order)
    return [_to_response(r) for r in rows]


def update_section(
    licitacion_id: str,
    user_id: str,
    section_id: str,
    patch: dict[str, Any],
    db: Session,
) -> MemoriaSectionResponse | None:
    """Actualiza campos parciales de una sección. None si no existe / no es del usuario."""
    row = (
        db.query(MemoriaSection)
        .filter(
            MemoriaSection.id == section_id,
            MemoriaSection.licitacion_id == licitacion_id,
            MemoriaSection.user_id == user_id,
        )
        .first()
    )
    if row is None:
        return None

    for field, value in patch.items():
        if value is not None and hasattr(row, field):
            setattr(row, field, value)
    # Una edición manual marca la sección como editada (salvo status explícito).
    if "status" not in patch:
        row.status = "edited"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _to_response(row)


def delete_section(licitacion_id: str, user_id: str, section_id: str, db: Session) -> bool:
    """Borra una sección. True si se borró, False si no existe / no es del usuario."""
    deleted = (
        db.query(MemoriaSection)
        .filter(
            MemoriaSection.id == section_id,
            MemoriaSection.licitacion_id == licitacion_id,
            MemoriaSection.user_id == user_id,
        )
        .delete()
    )
    db.commit()
    return deleted > 0
