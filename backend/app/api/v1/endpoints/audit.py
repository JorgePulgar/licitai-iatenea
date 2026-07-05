"""
Auditoría del sistema — GET /api/v1/system/audit (solo administradores).

Reescrito desde spec funcional (tarea 1.6, plan/phase-1-security.md):
- Auth obligatoria: `require_admin` (401 sin credenciales, 403 sin rol admin).
- Schemas de respuesta en `models/schemas.py` (contrato estable para el FE).
- Agregados por usuario en queries agrupadas (número fijo de queries,
  independiente del número de usuarios — sin N+1).
- Alcance mínimo: snapshot global de uso. El dashboard completo llega en 5.2.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.database import get_db
from app.models.domain import (
    CompanyTemplate,
    Licitacion,
    MemoriaChatMessage,
    MemoriaDocument,
    Pliego,
    Query,
    User,
)
from app.models.schemas import (
    AuditAIUsageStats,
    AuditDocumentStats,
    AuditLicitacionStats,
    AuditMemoriaStats,
    AuditResponse,
    AuditUserActivity,
    AuditUserStats,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _count_since(column, cutoff: datetime):
    """Cuenta filas con `column >= cutoff` dentro del mismo SELECT agregado."""
    return func.coalesce(func.sum(case((column >= cutoff, 1), else_=0)), 0)


def _licitacion_stats(
    db: Session, since_7d: datetime, since_30d: datetime
) -> AuditLicitacionStats:
    total, last_7d, last_30d = db.query(
        func.count(Licitacion.id),
        _count_since(Licitacion.created_at, since_7d),
        _count_since(Licitacion.created_at, since_30d),
    ).one()
    by_status = dict(
        db.query(Licitacion.status, func.count(Licitacion.id))
        .group_by(Licitacion.status)
        .all()
    )
    return AuditLicitacionStats(
        total=total,
        by_status=by_status,
        created_last_7d=last_7d,
        created_last_30d=last_30d,
    )


def _document_stats(db: Session) -> AuditDocumentStats:
    total, pages, size_bytes = db.query(
        func.count(Pliego.id),
        func.coalesce(func.sum(Pliego.page_count), 0),
        func.coalesce(func.sum(Pliego.size_bytes), 0),
    ).one()
    by_type = dict(
        db.query(Pliego.document_type, func.count(Pliego.id))
        .group_by(Pliego.document_type)
        .all()
    )
    return AuditDocumentStats(
        total_pliegos=total,
        total_pages=pages,
        total_size_mb=round(size_bytes / (1024 * 1024), 2),
        by_type=by_type,
    )


def _memoria_stats(db: Session) -> AuditMemoriaStats:
    return AuditMemoriaStats(
        total_documents=db.query(func.count(MemoriaDocument.id)).scalar() or 0,
        total_chat_messages=db.query(func.count(MemoriaChatMessage.id)).scalar() or 0,
        total_templates=db.query(func.count(CompanyTemplate.id)).scalar() or 0,
    )


def _ai_usage_stats(
    db: Session, since_7d: datetime, since_30d: datetime
) -> AuditAIUsageStats:
    total, tokens_prompt, tokens_completion, avg_latency, last_7d, last_30d = db.query(
        func.count(Query.id),
        func.coalesce(func.sum(Query.tokens_prompt), 0),
        func.coalesce(func.sum(Query.tokens_completion), 0),
        func.avg(Query.latency_ms),
        _count_since(Query.created_at, since_7d),
        _count_since(Query.created_at, since_30d),
    ).one()
    return AuditAIUsageStats(
        total_queries=total,
        total_tokens_prompt=tokens_prompt,
        total_tokens_completion=tokens_completion,
        total_tokens=tokens_prompt + tokens_completion,
        avg_latency_ms=round(avg_latency, 1) if avg_latency is not None else None,
        queries_last_7d=last_7d,
        queries_last_30d=last_30d,
    )


def _user_stats(db: Session) -> AuditUserStats:
    total, active = db.query(
        func.count(User.id),
        func.coalesce(
            func.sum(case((User.is_active == True, 1), else_=0)), 0  # noqa: E712
        ),
    ).one()
    return AuditUserStats(total_users=total, active_users=active)


def _user_activity(db: Session) -> list[AuditUserActivity]:
    """Actividad por usuario con dos queries agrupadas + una de usuarios (sin N+1)."""
    licitaciones_by_user = dict(
        db.query(Licitacion.user_id, func.count(Licitacion.id))
        .group_by(Licitacion.user_id)
        .all()
    )
    usage_by_user = {
        user_id: (n_queries, tokens)
        for user_id, n_queries, tokens in db.query(
            Query.user_id,
            func.count(Query.id),
            func.coalesce(func.sum(Query.tokens_prompt), 0)
            + func.coalesce(func.sum(Query.tokens_completion), 0),
        )
        .group_by(Query.user_id)
        .all()
    }

    activity: list[AuditUserActivity] = []
    for user_id, email, full_name in (
        db.query(User.id, User.email, User.full_name).order_by(User.email).all()
    ):
        n_queries, tokens = usage_by_user.get(user_id, (0, 0))
        activity.append(
            AuditUserActivity(
                user_id=user_id,
                email=email,
                full_name=full_name,
                licitaciones_count=licitaciones_by_user.get(user_id, 0),
                queries_count=n_queries,
                tokens_total=tokens,
            )
        )
    return activity


@router.get("/audit", response_model=AuditResponse)
def get_system_audit(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AuditResponse:
    """Snapshot global de uso del sistema. Requiere rol admin."""
    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    logger.info(
        "Auditoría de sistema generada",
        extra={"admin_user_id": str(admin.id)},
    )

    return AuditResponse(
        generated_at=now,
        licitaciones=_licitacion_stats(db, since_7d, since_30d),
        documents=_document_stats(db),
        memorias=_memoria_stats(db),
        ai_usage=_ai_usage_stats(db, since_7d, since_30d),
        users=_user_stats(db),
        user_activity=_user_activity(db),
    )
