"""
Chat de consultas RAG sobre una licitación — /api/v1/query.

Reescrito desde spec funcional (tarea 1.7 / DM2, plan/phase-1-security.md):
- POST /                 → respuesta LLM con citas; persiste el turno CON telemetría
                           (tokens_prompt, tokens_completion, latency_ms).
- GET /{id}/sessions     → hilos de conversación en UNA query agrupada (window
                           functions) + el check de propiedad: 2 queries en total.
- GET /{id}/history      → historial paginado (limit/offset), filtro opcional por hilo.

Comportamiento preservado: memoria del chat acotada por sesión (HISTORY_TURNS=6),
fallback de sesión heredada (session_id NULL), helper de aislamiento por propietario,
y un fallo al persistir el turno nunca tumba la respuesta al usuario — pero SIEMPRE
queda loggeado (nada de excepts silenciosos).
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Query as QueryParam
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user
from app.db.database import get_db
from app.models.domain import Licitacion, Query, User
from app.models.schemas import (
    Citation,
    QueryHistoryItem,
    QueryRequest,
    QueryResponse,
    QuerySession,
)
from app.services.query import LLM_MODEL, query_licitacion

logger = logging.getLogger(__name__)

router = APIRouter()

# Turnos previos (pregunta + respuesta) que se reinyectan al LLM como memoria del hilo.
HISTORY_TURNS = 6

# Estados de pipeline que permiten consultar (indexación completa o parcial).
_QUERYABLE_STATUSES = ("indexed", "partial_error")

HISTORY_DEFAULT_LIMIT = 100
HISTORY_MAX_LIMIT = 500


# ── Helpers ──────────────────────────────────────────────────────────────────


def _require_ownership(db: Session, licitacion_id: str, user_id: str) -> None:
    """404 si la licitación no existe o no es del usuario (aislamiento §10)."""
    owns = (
        db.query(Licitacion.id)
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == user_id)
        .first()
    )
    if not owns:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Licitación no encontrada",
        )


def _session_history(
    db: Session, licitacion_id: str, user_id: str, session_id: Optional[str]
) -> list[tuple[str, str]]:
    """Últimos HISTORY_TURNS turnos del hilo, en orden cronológico.

    Con session_id la memoria se acota al hilo (hilos distintos no se contaminan).
    Sin session_id se cae al comportamiento heredado: últimos turnos de la
    licitación, para las filas anteriores a las sesiones.
    """
    turns = db.query(Query.question, Query.answer).filter(
        Query.licitacion_id == licitacion_id,
        Query.user_id == user_id,
    )
    if session_id is not None:
        turns = turns.filter(Query.session_id == session_id)
    recent = (
        turns.order_by(Query.created_at.desc(), Query.id.desc())
        .limit(HISTORY_TURNS)
        .all()
    )
    return [(row.question, row.answer) for row in reversed(recent)]


def _persist_turn(
    db: Session,
    *,
    licitacion_id: str,
    user_id: str,
    body: QueryRequest,
    response: QueryResponse,
    latency_ms: int,
) -> None:
    """Guarda el turno con su telemetría (tokens y latencia, tarea 1.7).

    Si la persistencia falla, el usuario recibe igualmente su respuesta, pero el
    fallo queda registrado como ERROR — nunca se traga en silencio.
    """
    try:
        citations_json = json.dumps(
            [c.model_dump(mode="json") for c in response.citations]
        )
        db.add(
            Query(
                id=str(uuid.uuid4()),
                licitacion_id=licitacion_id,
                user_id=user_id,
                session_id=body.session_id,
                question=body.question,
                answer=response.answer,
                chunk_ids=citations_json,
                model_used=LLM_MODEL,
                tokens_prompt=response.tokens_prompt,
                tokens_completion=response.tokens_completion,
                latency_ms=latency_ms,
                had_citations=bool(response.citations),
                is_unanswerable=not response.citations,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "Fallo al persistir el turno de consulta; la respuesta se devuelve igualmente",
            exc_info=True,
            extra={"licitacion_id": licitacion_id, "session_id": body.session_id},
        )


def _to_history_item(row: Query) -> QueryHistoryItem:
    citations: List[Citation] = []
    if row.chunk_ids:
        try:
            citations = [Citation(**c) for c in json.loads(row.chunk_ids)]
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Citas ilegibles en el historial; se devuelven vacías",
                extra={"query_row_id": row.id},
            )
    return QueryHistoryItem(
        id=row.id,
        question=row.question,
        answer=row.answer,
        citations=citations,
        created_at=row.created_at,
        session_id=row.session_id,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/", response_model=QueryResponse)
async def ask_question(
    body: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    """Consulta en lenguaje natural sobre los documentos indexados de la licitación.

    Devuelve la respuesta del LLM con citas inline [doc p. N] y persiste el turno
    (con hilo, tokens y latencia) para el historial y el reporting de uso.
    """
    licitacion = (
        db.query(Licitacion)
        .options(selectinload(Licitacion.documents))
        .filter(
            Licitacion.id == body.licitacion_id,
            Licitacion.user_id == current_user.id,
        )
        .first()
    )
    if not licitacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Licitación no encontrada",
        )
    if licitacion.status not in _QUERYABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La licitación no está indexada (estado actual: {licitacion.status})",
        )

    page_counts = {
        p.id: p.page_count for p in licitacion.documents if p.page_count is not None
    }
    history = _session_history(db, licitacion.id, current_user.id, body.session_id)

    t_start = time.monotonic()
    response = await query_licitacion(
        question=body.question,
        licitacion_id=licitacion.id,
        user_id=current_user.id,
        title=licitacion.title,
        document_type=body.document_type,
        page_counts=page_counts,
        history=history,
    )
    latency_ms = int((time.monotonic() - t_start) * 1000)

    _persist_turn(
        db,
        licitacion_id=licitacion.id,
        user_id=current_user.id,
        body=body,
        response=response,
        latency_ms=latency_ms,
    )
    return response


@router.get("/{licitacion_id}/sessions", response_model=List[QuerySession])
def list_sessions(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[QuerySession]:
    """Hilos de conversación de la licitación, del más reciente al más antiguo.

    Una sola query agrupada: las window functions calculan por hilo el contador,
    las fechas y el rango de cada turno; la fila con rango 1 aporta la primera
    pregunta como rótulo. Los turnos heredados (session_id NULL) se omiten.
    """
    _require_ownership(db, licitacion_id, current_user.id)

    turns = (
        db.query(
            Query.session_id.label("session_id"),
            Query.question.label("question"),
            func.row_number()
            .over(
                partition_by=Query.session_id,
                order_by=(Query.created_at.asc(), Query.id.asc()),
            )
            .label("turn_rank"),
            func.count()
            .over(partition_by=Query.session_id)
            .label("message_count"),
            func.min(Query.created_at)
            .over(partition_by=Query.session_id)
            .label("started_at"),
            func.max(Query.created_at)
            .over(partition_by=Query.session_id)
            .label("last_activity"),
        )
        .filter(
            Query.licitacion_id == licitacion_id,
            Query.user_id == current_user.id,
            Query.session_id.isnot(None),
        )
        .subquery()
    )
    rows = (
        db.query(turns)
        .filter(turns.c.turn_rank == 1)
        .order_by(turns.c.last_activity.desc())
        .all()
    )

    return [
        QuerySession(
            session_id=row.session_id,
            title=row.question,
            message_count=row.message_count,
            created_at=row.started_at,
            updated_at=row.last_activity,
        )
        for row in rows
    ]


@router.get("/{licitacion_id}/history", response_model=List[QueryHistoryItem])
def get_history(
    licitacion_id: str,
    session_id: Optional[str] = None,
    limit: int = QueryParam(default=HISTORY_DEFAULT_LIMIT, ge=1, le=HISTORY_MAX_LIMIT),
    offset: int = QueryParam(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[QueryHistoryItem]:
    """Historial de la licitación en orden cronológico, paginado (limit/offset).

    Con session_id se limita a ese hilo; sin él devuelve todos los turnos,
    incluida la sesión heredada (session_id NULL).
    """
    _require_ownership(db, licitacion_id, current_user.id)

    turns = db.query(Query).filter(
        Query.licitacion_id == licitacion_id,
        Query.user_id == current_user.id,
    )
    if session_id is not None:
        turns = turns.filter(Query.session_id == session_id)
    rows = (
        turns.order_by(Query.created_at.asc(), Query.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_to_history_item(row) for row in rows]
