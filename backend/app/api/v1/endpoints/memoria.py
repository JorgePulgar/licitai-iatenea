"""
Endpoints de la Memoria Técnica (flujo completo, ADR-002).

Rutas bajo /api/v1/licitaciones/{licitacion_id}/memoria. Clave de sesión:
licitacion_id + user_id (sin session_id). Todas verifican propiedad por user_id (§10).

Flujo:
  POST /esquema    → estructura de secciones (agente esquema)
  POST /propuesta  → redacta el Markdown desde el esquema (agente propuesta)
  POST /chat       → edita el Markdown vía chat (agente conversacional)
  POST /export     → Markdown → PDF
Más CRUD del esquema (/sections), historial (/chat GET) y lectura del documento.
Ver docs/ADR/ADR-002-memoria-tecnica-flujo-completo.md.
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.database import SessionLocal, get_db
from app.models.domain import CompanyProfile, Licitacion, User
from app.models.schemas import (
    MemoriaChatMessageResponse,
    MemoriaDocChatRequest,
    MemoriaDocChatResponse,
    MemoriaDocumentResponse,
    MemoriaEsquemaRequest,
    MemoriaEsquemaResponse,
    MemoriaDocumentPatch,
    MemoriaExportRequest,
    MemoriaPropuestaRequest,
    MemoriaPropuestaResponse,
    MemoriaSectionPatch,
    MemoriaSectionResponse,
    MemoriaSectionsSaveRequest,
)
from app.services import memoria as memoria_service

router = APIRouter()


def _get_owned_licitacion(licitacion_id: str, user_id: str, db: Session) -> Licitacion:
    """Devuelve la licitación si pertenece al usuario; 404 en caso contrario."""
    licitacion = (
        db.query(Licitacion)
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == user_id)
        .first()
    )
    if not licitacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Licitación no encontrada",
        )
    return licitacion


# ── Fase 1: esquema (estructura) ─────────────────────────────────────────────

@router.post("/{licitacion_id}/memoria/esquema", response_model=MemoriaEsquemaResponse)
async def propose_esquema(
    licitacion_id: str,
    body: MemoriaEsquemaRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaEsquemaResponse:
    """Propone (sin persistir) la estructura de secciones a partir del mensaje del usuario."""
    licitacion = _get_owned_licitacion(licitacion_id, current_user.id, db)
    return await memoria_service.propose_esquema(
        licitacion_id=licitacion_id,
        user_id=current_user.id,
        title=licitacion.title,
        user_message=body.message,
        db=db,
        template_ids=body.template_ids,
    )


@router.get("/{licitacion_id}/memoria/sections", response_model=List[MemoriaSectionResponse])
def list_sections(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MemoriaSectionResponse]:
    """Esquema persistido (secciones aceptadas), ordenado."""
    _get_owned_licitacion(licitacion_id, current_user.id, db)
    return memoria_service.get_sections(licitacion_id, current_user.id, db)


@router.post(
    "/{licitacion_id}/memoria/sections",
    response_model=List[MemoriaSectionResponse],
    status_code=status.HTTP_201_CREATED,
)
def save_sections(
    licitacion_id: str,
    body: MemoriaSectionsSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MemoriaSectionResponse]:
    """Persiste/acepta el esquema (reemplaza el anterior)."""
    _get_owned_licitacion(licitacion_id, current_user.id, db)
    return memoria_service.save_sections(licitacion_id, current_user.id, body.sections, db)


@router.patch(
    "/{licitacion_id}/memoria/sections/{section_id}",
    response_model=MemoriaSectionResponse,
)
def patch_section(
    licitacion_id: str,
    section_id: str,
    body: MemoriaSectionPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaSectionResponse:
    """Edita campos parciales de una sección."""
    _get_owned_licitacion(licitacion_id, current_user.id, db)
    updated = memoria_service.update_section(
        licitacion_id, current_user.id, section_id, body.model_dump(exclude_unset=True), db
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sección no encontrada")
    return updated


@router.delete(
    "/{licitacion_id}/memoria/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_section(
    licitacion_id: str,
    section_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Borra una sección del esquema."""
    _get_owned_licitacion(licitacion_id, current_user.id, db)
    deleted = memoria_service.delete_section(licitacion_id, current_user.id, section_id, db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sección no encontrada")
    return None


# ── Fase 2: propuesta (redacción del Markdown) ──────────────────────────────

@router.post("/{licitacion_id}/memoria/propuesta", response_model=MemoriaPropuestaResponse)
async def generate_propuesta(
    licitacion_id: str,
    body: MemoriaPropuestaRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaPropuestaResponse:
    """Redacta la Memoria Técnica en Markdown desde el esquema aprobado (grounded en PPT + perfil)."""
    licitacion = _get_owned_licitacion(licitacion_id, current_user.id, db)
    doc = await memoria_service.generate_propuesta(
        licitacion_id=licitacion_id,
        user_id=current_user.id,
        title=licitacion.title,
        esquema=body.esquema,
        db=db,
        session_factory=SessionLocal,
        template_ids=body.template_ids,
    )
    return MemoriaPropuestaResponse(doc_id=doc.id, title=doc.title, markdown=doc.markdown)


@router.get("/{licitacion_id}/memoria/documents", response_model=List[MemoriaDocumentResponse])
def get_documents(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MemoriaDocumentResponse]:
    """Devuelve la lista de documentos Markdown persistidos."""
    _get_owned_licitacion(licitacion_id, current_user.id, db)
    docs = memoria_service.get_documents(licitacion_id, current_user.id, db)
    return [MemoriaDocumentResponse.model_validate(doc) for doc in docs]


@router.get("/{licitacion_id}/memoria/documents/{doc_id}", response_model=MemoriaDocumentResponse)
def get_document_by_id(
    licitacion_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaDocumentResponse:
    """Devuelve el Markdown de un documento específico."""
    _get_owned_licitacion(licitacion_id, current_user.id, db)
    doc = memoria_service.get_document_by_id(doc_id, licitacion_id, current_user.id, db)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return MemoriaDocumentResponse.model_validate(doc)


@router.patch(
    "/{licitacion_id}/memoria/documents/{doc_id}",
    response_model=MemoriaDocumentResponse,
)
def patch_document(
    licitacion_id: str,
    doc_id: str,
    body: MemoriaDocumentPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaDocumentResponse:
    """Actualiza title/markdown del documento (edición manual desde el editor)."""
    _get_owned_licitacion(licitacion_id, current_user.id, db)
    updated = memoria_service.update_document(
        doc_id=doc_id,
        licitacion_id=licitacion_id,
        user_id=current_user.id,
        title=body.title,
        markdown=body.markdown,
        db=db,
        session_factory=SessionLocal,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return MemoriaDocumentResponse.model_validate(updated)


# ── Fase 3: chat de refinado sobre el Markdown ──────────────────────────────

@router.post("/{licitacion_id}/memoria/chat", response_model=MemoriaDocChatResponse)
async def chat_edit(
    licitacion_id: str,
    body: MemoriaDocChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaDocChatResponse:
    """Edita el Markdown según la petición del usuario, con histórico y grounding."""
    licitacion = _get_owned_licitacion(licitacion_id, current_user.id, db)
    new_markdown, texto_chat = await memoria_service.edit_propuesta_chat(
        doc_id=body.doc_id,
        licitacion_id=licitacion_id,
        user_id=current_user.id,
        title=licitacion.title,
        markdown=body.markdown,
        message=body.message,
        db=db,
        session_factory=SessionLocal,
    )
    return MemoriaDocChatResponse(markdown=new_markdown, texto_chat=texto_chat)


@router.get("/{licitacion_id}/memoria/chat", response_model=List[MemoriaChatMessageResponse])
def chat_history(
    licitacion_id: str,
    doc_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MemoriaChatMessageResponse]:
    """Historial del chat de refinado, opcionalmente filtrado por versión del documento."""
    _get_owned_licitacion(licitacion_id, current_user.id, db)
    rows = memoria_service.get_chat_history(
        licitacion_id, current_user.id, db, doc_id=doc_id
    )
    return [MemoriaChatMessageResponse.model_validate(r) for r in rows]


# ── Fase 4: export a PDF ─────────────────────────────────────────────────────

@router.post("/{licitacion_id}/memoria/export")
def export_pdf(
    licitacion_id: str,
    body: MemoriaExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Exporta el Markdown (del body o el persistido) a PDF."""
    licitacion = _get_owned_licitacion(licitacion_id, current_user.id, db)

    markdown = body.markdown
    document_title = ""
    if markdown is None and body.doc_id:
        doc = memoria_service.get_document_by_id(body.doc_id, licitacion_id, current_user.id, db)
        markdown = doc.markdown if doc else None
        document_title = doc.title if doc else ""
    if not markdown:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay documento que exportar.",
        )

    from app.services.memoria_export import render_markdown_pdf

    try:
        company = (
            db.query(CompanyProfile)
            .filter(
                CompanyProfile.created_by == current_user.id,
                CompanyProfile.is_default == True,  # noqa: E712
            )
            .first()
        )
        now = datetime.now()
        pdf_bytes = render_markdown_pdf(
            markdown,
            variables={
                "current_date": now.strftime("%d/%m/%Y"),
                "current_year": str(now.year),
                "company_name": company.name if company else "",
                "tender_title": licitacion.title,
                "document_title": document_title,
                "user_name": current_user.full_name or current_user.email,
                "user_email": current_user.email,
            },
        )
    except OSError as e:
        # WeasyPrint requiere libs nativas (GTK/Pango). Falla en dev Windows sin GTK.
        from app.core.logging import get_logger
        get_logger(__name__).error(f"PDF export failed (native libs missing?): {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export a PDF no disponible: faltan librerías nativas de WeasyPrint (GTK/Pango). "
                   "Ver docs de instalación.",
        )

    filename = f"memoria_{licitacion_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
