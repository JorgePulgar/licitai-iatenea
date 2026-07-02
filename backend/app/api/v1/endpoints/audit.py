"""
Endpoint de auditoría del sistema.

Devuelve un snapshot con métricas generales: licitaciones, documentos,
memorias, consultas IA, tokens consumidos y uso por usuario.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, case, distinct
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.domain import (
    Licitacion, Pliego, User, Query,
    MemoriaDocument, MemoriaChatMessage, CompanyTemplate,
)

router = APIRouter()


# ── Response schemas ─────────────────────────────────────────────────────────

class LicitacionStats(BaseModel):
    total: int
    by_status: dict[str, int]
    created_last_7d: int
    created_last_30d: int


class DocumentStats(BaseModel):
    total_pliegos: int
    total_pages: int
    total_size_mb: float
    by_type: dict[str, int]


class MemoriaStats(BaseModel):
    total_documents: int
    total_chat_messages: int
    total_templates: int


class AIUsageStats(BaseModel):
    total_queries: int
    total_tokens_prompt: int
    total_tokens_completion: int
    total_tokens: int
    avg_latency_ms: Optional[float]
    queries_last_7d: int
    queries_last_30d: int


class UserStats(BaseModel):
    total_users: int
    active_users: int


class UserActivity(BaseModel):
    user_id: str
    email: str
    full_name: Optional[str]
    licitaciones_count: int
    queries_count: int
    tokens_total: int


class AuditResponse(BaseModel):
    generated_at: str
    licitaciones: LicitacionStats
    documents: DocumentStats
    memorias: MemoriaStats
    ai_usage: AIUsageStats
    users: UserStats
    user_activity: list[UserActivity]


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/audit", response_model=AuditResponse)
def get_system_audit(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    # ── Licitaciones ─────────────────────────────────────────────────────
    lic_total = db.query(func.count(Licitacion.id)).scalar() or 0
    lic_by_status_rows = (
        db.query(Licitacion.status, func.count(Licitacion.id))
        .group_by(Licitacion.status)
        .all()
    )
    lic_by_status = {row[0]: row[1] for row in lic_by_status_rows}
    lic_7d = (
        db.query(func.count(Licitacion.id))
        .filter(Licitacion.created_at >= seven_days_ago)
        .scalar() or 0
    )
    lic_30d = (
        db.query(func.count(Licitacion.id))
        .filter(Licitacion.created_at >= thirty_days_ago)
        .scalar() or 0
    )

    # ── Documentos (pliegos) ─────────────────────────────────────────────
    pliego_total = db.query(func.count(Pliego.id)).scalar() or 0
    pliego_pages = db.query(func.coalesce(func.sum(Pliego.page_count), 0)).scalar() or 0
    pliego_size = db.query(func.coalesce(func.sum(Pliego.size_bytes), 0)).scalar() or 0
    pliego_by_type_rows = (
        db.query(Pliego.document_type, func.count(Pliego.id))
        .group_by(Pliego.document_type)
        .all()
    )
    pliego_by_type = {row[0]: row[1] for row in pliego_by_type_rows}

    # ── Memorias ─────────────────────────────────────────────────────────
    mem_docs = db.query(func.count(MemoriaDocument.id)).scalar() or 0
    mem_chats = db.query(func.count(MemoriaChatMessage.id)).scalar() or 0
    mem_templates = db.query(func.count(CompanyTemplate.id)).scalar() or 0

    # ── AI / Queries ─────────────────────────────────────────────────────
    q_total = db.query(func.count(Query.id)).scalar() or 0
    q_tok_prompt = db.query(func.coalesce(func.sum(Query.tokens_prompt), 0)).scalar() or 0
    q_tok_completion = db.query(func.coalesce(func.sum(Query.tokens_completion), 0)).scalar() or 0
    q_avg_latency = db.query(func.avg(Query.latency_ms)).scalar()
    q_7d = (
        db.query(func.count(Query.id))
        .filter(Query.created_at >= seven_days_ago)
        .scalar() or 0
    )
    q_30d = (
        db.query(func.count(Query.id))
        .filter(Query.created_at >= thirty_days_ago)
        .scalar() or 0
    )

    # ── Users ────────────────────────────────────────────────────────────
    u_total = db.query(func.count(User.id)).scalar() or 0
    u_active = (
        db.query(func.count(User.id))
        .filter(User.is_active == True)  # noqa: E712
        .scalar() or 0
    )

    # ── Per-user activity ────────────────────────────────────────────────
    user_rows = db.query(User.id, User.email, User.full_name).all()
    user_activity: list[UserActivity] = []
    for uid, email, name in user_rows:
        u_lic = (
            db.query(func.count(Licitacion.id))
            .filter(Licitacion.user_id == uid)
            .scalar() or 0
        )
        u_q = (
            db.query(func.count(Query.id))
            .filter(Query.user_id == uid)
            .scalar() or 0
        )
        u_tok = (
            db.query(
                func.coalesce(func.sum(Query.tokens_prompt), 0)
                + func.coalesce(func.sum(Query.tokens_completion), 0)
            )
            .filter(Query.user_id == uid)
            .scalar() or 0
        )
        user_activity.append(UserActivity(
            user_id=uid,
            email=email,
            full_name=name,
            licitaciones_count=u_lic,
            queries_count=u_q,
            tokens_total=u_tok,
        ))

    return AuditResponse(
        generated_at=now.isoformat(),
        licitaciones=LicitacionStats(
            total=lic_total,
            by_status=lic_by_status,
            created_last_7d=lic_7d,
            created_last_30d=lic_30d,
        ),
        documents=DocumentStats(
            total_pliegos=pliego_total,
            total_pages=pliego_pages,
            total_size_mb=round(pliego_size / (1024 * 1024), 2),
            by_type=pliego_by_type,
        ),
        memorias=MemoriaStats(
            total_documents=mem_docs,
            total_chat_messages=mem_chats,
            total_templates=mem_templates,
        ),
        ai_usage=AIUsageStats(
            total_queries=q_total,
            total_tokens_prompt=q_tok_prompt,
            total_tokens_completion=q_tok_completion,
            total_tokens=q_tok_prompt + q_tok_completion,
            avg_latency_ms=round(q_avg_latency, 1) if q_avg_latency else None,
            queries_last_7d=q_7d,
            queries_last_30d=q_30d,
        ),
        users=UserStats(
            total_users=u_total,
            active_users=u_active,
        ),
        user_activity=user_activity,
    )
