import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.domain import PliegoRequirement
from app.models.schemas import RequirementResponse, RequirementsListResponse
from app.prompts.requirements import REQUIREMENTS_SYSTEM_PROMPT
from app.services.embeddings import get_openai_client
from app.services.query import hybrid_search

logger = get_logger(__name__)

LLM_MODEL = "extraccion_datos_4o"
LLM_TEMPERATURE = 0.2

# Each query retrieves top_k chunks via semantic search.
# With 18 queries × 15 top_k = up to 270 candidate chunks (deduplicated).
RETRIEVAL_TOP_K = 15

# Targeted queries that cover all requirement categories.
# Each query is phrased as a QUESTION to maximize semantic match with
# substantive content (not table of contents headings).
_REQUIREMENTS_QUERIES = [
    # Administrativo
    "¿Cuál es el plazo de presentación de ofertas y qué documentación administrativa se requiere?",
    "¿Qué garantía provisional o definitiva se exige y de qué porcentaje?",
    "¿Se exige clasificación empresarial? ¿Qué grupo, subgrupo y categoría?",
    "¿Se permite la subcontratación? ¿Qué límites tiene? ¿Se permiten UTEs?",
    # Solvencia técnica
    "¿Qué experiencia mínima en contratos similares se requiere? ¿Importe y años?",
    "¿Qué equipo técnico mínimo se exige? ¿Perfiles, titulación, experiencia?",
    "¿Qué certificaciones son obligatorias? ¿ISO, ENS, otras?",
    "¿Qué medios materiales o infraestructura técnica se exigen?",
    # Solvencia económica
    "¿Cuál es la cifra de negocio mínima exigida? ¿Qué seguro de responsabilidad civil se requiere?",
    # Técnico / PPT
    "¿Cuáles son las prestaciones obligatorias del servicio? ¿Qué hay que hacer exactamente?",
    "¿Qué niveles de servicio SLA se exigen? ¿Disponibilidad, tiempos de respuesta?",
    "¿Qué penalizaciones hay por incumplimiento? ¿Importes o porcentajes de deducción?",
    "¿Qué entregables o documentación se deben presentar? ¿Plan de trabajo, memorias?",
    "¿Cuál es el plazo de ejecución del contrato? ¿Hitos, fases, cronograma?",
    # Criterios de adjudicación
    "¿Cuáles son los criterios de adjudicación y su puntuación máxima?",
    "¿Qué criterios son de juicio de valor? ¿Memoria técnica, metodología, mejoras?",
    "¿Cuál es la fórmula de valoración del precio? ¿Criterios automáticos?",
    "¿Cuál es el presupuesto base de licitación? ¿Valor estimado del contrato?",
]


async def extract_requirements(
    licitacion_id: str,
    user_id: str,
    title: str,
    db: Session,
    session_factory: Callable[[], Session] | None = None,
) -> RequirementsListResponse:
    """
    Extracts requirements from a licitacion's documents via LLM.
    Uses multi-query semantic search to gather diverse, high-quality chunks
    from across the full document, then sends them to the LLM.

    The DB session passed in ``db`` is used only for the initial cache check.
    A **fresh** session (from ``session_factory``) is opened right before
    persisting results, so that the connection isn't held open during the
    long-running search + LLM call (which can take minutes and cause the
    SQL Server TCP connection to go stale).
    """
    existing = (
        db.query(PliegoRequirement)
        .filter(PliegoRequirement.licitacion_id == licitacion_id)
        .all()
    )
    if existing:
        return RequirementsListResponse(
            licitacion_id=licitacion_id,
            requirements=[_to_response(r) for r in existing],
            cached=True,
            generated_at=existing[0].generated_at,
        )

    # Multi-query semantic search: each query targets a different category
    # of requirements to maximize coverage across the full document.
    seen_ids: set[str] = set()
    all_chunks: list[dict[str, Any]] = []

    for q in _REQUIREMENTS_QUERIES:
        results = await hybrid_search(q, licitacion_id, user_id, top_k=RETRIEVAL_TOP_K)
        for chunk in results:
            cid = chunk.get("chunk_id") or chunk.get("text", "")[:80]
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_chunks.append(chunk)

    if not all_chunks:
        logger.warning(f"No chunks found for requirements of licitacion {licitacion_id}.")
        return RequirementsListResponse(
            licitacion_id=licitacion_id,
            requirements=[],
            cached=False,
        )

    # Sort by document type then page for coherent reading order
    all_chunks.sort(key=lambda c: (c.get("document_type", ""), c.get("page_number") or 0))

    # Log stats
    text_lengths = [len(c.get("text", "")) for c in all_chunks]
    distinct_pages = len(set(
        (c.get("document_type", ""), c.get("page_number"))
        for c in all_chunks
    ))
    logger.info(
        f"Requirements retrieval: {len(all_chunks)} unique chunks from "
        f"{distinct_pages} distinct pages. "
        f"Text: min={min(text_lengths)}, max={max(text_lengths)}, "
        f"avg={sum(text_lengths) // len(text_lengths)}, "
        f"total={sum(text_lengths)} chars. "
        f"Licitacion: {licitacion_id}"
    )

    # Build context in reading order
    context = "\n\n".join(
        f"[{c.get('document_type', '')} p. {c.get('page_number', '?')}] {c['text']}"
        for c in all_chunks
    )

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI not configured — requirements extraction unavailable.")
        return RequirementsListResponse(
            licitacion_id=licitacion_id,
            requirements=[],
            cached=False,
        )

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": REQUIREMENTS_SYSTEM_PROMPT},
                {"role": "user", "content": f"Licitación: '{title}'\n\nFragmentos del pliego ({len(all_chunks)} fragmentos):\n\n{context}"},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        finish_reason = response.choices[0].finish_reason

        logger.info(
            f"LLM response: context={len(context)} chars, "
            f"finish_reason={finish_reason}, response_len={len(raw)}"
        )

        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {e}. Raw: {raw[:300]}")
        raise
    except Exception as e:
        logger.error(f"Error extracting requirements for licitacion {licitacion_id}: {e}")
        raise

    now = datetime.now(timezone.utc)
    raw_requirements = data.get("requisitos", [])

    # Deduplicate by normalized description
    seen_descs: set[str] = set()
    db_records: list[PliegoRequirement] = []
    response_items: list[RequirementResponse] = []

    for req in raw_requirements:
        desc = req.get("descripcion", "").strip()
        key = " ".join(desc.lower().split())
        if not key or key in seen_descs:
            continue
        seen_descs.add(key)

        record = PliegoRequirement(
            id=str(uuid.uuid4()),
            licitacion_id=licitacion_id,
            categoria=req.get("categoria", "tecnico"),
            descripcion=desc,
            pagina=req.get("pagina"),
            documento_origen=req.get("documento_origen", "pcap"),
            es_obligatorio=req.get("es_obligatorio", True),
            generated_at=now,
        )
        db_records.append(record)
        response_items.append(_to_response(record))

    # Persist with a FRESH session to avoid stale TCP connections.
    # The original session has been idle during search + LLM (potentially
    # minutes), so SQL Server may have dropped the underlying connection.
    write_db = session_factory() if session_factory else db
    try:
        for record in db_records:
            write_db.add(record)
        write_db.commit()
    except Exception:
        write_db.rollback()
        raise
    finally:
        if write_db is not db:
            write_db.close()

    logger.info(
        f"Extracted {len(raw_requirements)} raw → {len(db_records)} unique requirements "
        f"for licitacion {licitacion_id}."
    )

    return RequirementsListResponse(
        licitacion_id=licitacion_id,
        requirements=response_items,
        cached=False,
        generated_at=now,
    )


def _to_response(record: PliegoRequirement) -> RequirementResponse:
    return RequirementResponse(
        id=record.id,
        categoria=record.categoria,
        descripcion=record.descripcion,
        pagina=record.pagina,
        documento_origen=record.documento_origen,
        es_obligatorio=record.es_obligatorio,
    )
