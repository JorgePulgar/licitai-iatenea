import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services.query import query_licitacion, LLM_MODEL

router = APIRouter()

# Cuántos turnos previos (pregunta + respuesta) se reinyectan al LLM como memoria.
HISTORY_TURNS = 6


@router.post("/", response_model=QueryResponse)
async def query_endpoint(
    body: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    """
    Natural language query over a licitacion's indexed documents.
    Returns an LLM answer with inline citations [document_type p. N].
    Optionally filter by document_type (pcap | ppt | anexo).
    Persists the query and answer to the database for conversation history.
    """
    licitacion = (
        db.query(Licitacion)
        .options(selectinload(Licitacion.documents))
        .filter(Licitacion.id == body.licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Licitación no encontrada",
        )

    if licitacion.status not in ("indexed", "partial_error"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La licitación no está indexada (estado actual: {licitacion.status})",
        )

    page_counts = {
        p.id: p.page_count
        for p in licitacion.documents
        if p.page_count is not None
    }

    # Memoria del chat acotada al HILO (session_id): solo los turnos previos de esta
    # sesión se reinyectan al LLM, así "Nueva conversación" arranca sin contexto y los
    # hilos no se contaminan entre sí. Sin session_id se cae al comportamiento heredado
    # (últimos turnos de la licitación) por compatibilidad.
    recent_q = db.query(Query).filter(
        Query.licitacion_id == licitacion.id,
        Query.user_id == current_user.id,
    )
    if body.session_id is not None:
        recent_q = recent_q.filter(Query.session_id == body.session_id)
    recent = recent_q.order_by(Query.created_at.desc()).limit(HISTORY_TURNS).all()
    history = [(row.question, row.answer) for row in reversed(recent)]

    response = await query_licitacion(
        question=body.question,
        licitacion_id=licitacion.id,
        user_id=current_user.id,
        title=licitacion.title,
        document_type=body.document_type,
        page_counts=page_counts,
        history=history,
    )

    # Persist to DB (incluye el hilo al que pertenece el turno).
    try:
        citations_json = json.dumps(
            [c.model_dump(mode="json") for c in response.citations]
        )
        query_row = Query(
            id=str(uuid.uuid4()),
            licitacion_id=licitacion.id,
            user_id=current_user.id,
            session_id=body.session_id,
            question=body.question,
            answer=response.answer,
            chunk_ids=citations_json,
            model_used=LLM_MODEL,
            had_citations=len(response.citations) > 0,
            is_unanswerable=len(response.citations) == 0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(query_row)
        db.commit()
    except Exception:
        db.rollback()
        # Don't fail the request if persistence fails — the user still gets their answer

    return response


def _verify_ownership(licitacion_id: str, user_id: str, db: Session) -> None:
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


@router.get("/{licitacion_id}/sessions", response_model=List[QuerySession])
def query_sessions(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[QuerySession]:
    """
    Lista los hilos de conversación de la licitación (agrupados por session_id), del
    más reciente al más antiguo. Los turnos heredados sin session_id (NULL) se omiten
    del listado: pertenecen a la "sesión heredada" anterior a esta funcionalidad.
    """
    _verify_ownership(licitacion_id, current_user.id, db)

    rows = (
        db.query(
            Query.session_id.label("session_id"),
            func.count().label("message_count"),
            func.min(Query.created_at).label("created_at"),
            func.max(Query.created_at).label("updated_at"),
        )
        .filter(
            Query.licitacion_id == licitacion_id,
            Query.user_id == current_user.id,
            Query.session_id.isnot(None),
        )
        .group_by(Query.session_id)
        .order_by(func.max(Query.created_at).desc())
        .all()
    )

    # La primera pregunta de cada hilo sirve de rótulo (una consulta por sesión).
    first_questions: dict[str, str] = {}
    for r in rows:
        first = (
            db.query(Query.question)
            .filter(
                Query.licitacion_id == licitacion_id,
                Query.user_id == current_user.id,
                Query.session_id == r.session_id,
            )
            .order_by(Query.created_at.asc())
            .first()
        )
        first_questions[r.session_id] = first.question if first else "Consulta"

    return [
        QuerySession(
            session_id=r.session_id,
            title=first_questions.get(r.session_id, "Consulta"),
            message_count=r.message_count,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/{licitacion_id}/history", response_model=List[QueryHistoryItem])
def query_history(
    licitacion_id: str,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[QueryHistoryItem]:
    """
    Devuelve el historial de la licitación, en orden cronológico. Si se pasa
    ``session_id``, se limita a ese hilo; si no, devuelve todo (incluida la sesión
    heredada sin session_id).
    """
    _verify_ownership(licitacion_id, current_user.id, db)

    q = db.query(Query).filter(
        Query.licitacion_id == licitacion_id, Query.user_id == current_user.id
    )
    if session_id is not None:
        q = q.filter(Query.session_id == session_id)
    rows = q.order_by(Query.created_at.asc()).all()

    items: List[QueryHistoryItem] = []
    for row in rows:
        citations: List[Citation] = []
        if row.chunk_ids:
            try:
                raw = json.loads(row.chunk_ids)
                citations = [Citation(**c) for c in raw]
            except (json.JSONDecodeError, TypeError):
                pass

        items.append(
            QueryHistoryItem(
                id=row.id,
                question=row.question,
                answer=row.answer,
                citations=citations,
                created_at=row.created_at,
                session_id=row.session_id,
            )
        )

    return items
