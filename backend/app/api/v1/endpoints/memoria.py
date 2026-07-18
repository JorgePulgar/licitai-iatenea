"""
Endpoints de Memoria Técnica — reescritos desde spec funcional (DM5, spec-demo-minimal §2).

Rutas bajo ``/api/v1/licitaciones/{licitacion_id}/memoria``. Toda ruta verifica que la
licitación pertenece al usuario autenticado (404 en caso contrario, §10).

Contrato:
  POST /esquema                → propone estructura (no persiste)      {reply, esquema[]}
  GET/POST /sections           → esquema persistido (lista / reemplaza)
  PATCH/DELETE /sections/{id}  → edición / borrado de una sección
  POST /propuesta              → redacta el Markdown completo (síncrono) {doc_id, title, markdown}
  GET /documents[/{id}]        → documentos persistidos
  PATCH /documents/{id}        → edición manual (autosave del editor)
  POST /chat                   → edita el Markdown vía chat            {markdown, texto_chat}
  GET /chat[?doc_id=]          → historial del chat de refinado
  POST /export                 → Markdown → PDF o DOCX (servicio 5.6 ♻; format, TOC, header/footer)

Sin plantillas de referencia (CompanyTemplate): flujo 3.2b, fuera de la ruta de demo.
Ejecución síncrona sin cola (la cola llega en 4.1; el servicio ya es invocable desde
un worker sin cambios).
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
    MemoriaCoherenciaResponse,
    MemoriaDocChatRequest,
    MemoriaDocChatResponse,
    MemoriaDocumentPatch,
    MemoriaDocumentResponse,
    MemoriaEsquemaRequest,
    MemoriaEsquemaResponse,
    MemoriaExportRequest,
    MemoriaPropuestaRequest,
    MemoriaPropuestaResponse,
    MemoriaSectionPatch,
    MemoriaSectionResponse,
    MemoriaSectionsSaveRequest,
)
from app.services import memoria

router = APIRouter()


def _owned_licitacion_or_404(licitacion_id: str, user_id: str, db: Session) -> Licitacion:
    """Licitación del usuario, o 404 (no filtra por estado: la memoria es editable siempre)."""
    row = (
        db.query(Licitacion)
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == user_id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada"
        )
    return row


# ── Esquema ──────────────────────────────────────────────────────────────────

@router.post("/{licitacion_id}/memoria/esquema", response_model=MemoriaEsquemaResponse)
async def propose_esquema(
    licitacion_id: str,
    body: MemoriaEsquemaRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaEsquemaResponse:
    """Propone (sin persistir) la estructura de secciones de la Memoria."""
    licitacion = _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    return await memoria.propose_esquema(
        licitacion_id=licitacion_id,
        user_id=current_user.id,
        title=licitacion.title,
        user_message=body.message,
        db=db,
    )


@router.get("/{licitacion_id}/memoria/sections", response_model=List[MemoriaSectionResponse])
def list_sections(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MemoriaSectionResponse]:
    """Esquema persistido (secciones aceptadas), ordenado."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    return memoria.get_sections(licitacion_id, current_user.id, db)


@router.post(
    "/{licitacion_id}/memoria/sections",
    response_model=List[MemoriaSectionResponse],
    status_code=status.HTTP_201_CREATED,
)
def replace_sections(
    licitacion_id: str,
    body: MemoriaSectionsSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MemoriaSectionResponse]:
    """Acepta el esquema: reemplaza íntegramente las secciones anteriores."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    return memoria.save_sections(licitacion_id, current_user.id, body.sections, db)


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
    """Edición parcial de una sección del esquema."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    updated = memoria.update_section(
        licitacion_id, current_user.id, section_id, body.model_dump(exclude_unset=True), db
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sección no encontrada")
    return updated


@router.delete(
    "/{licitacion_id}/memoria/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_section(
    licitacion_id: str,
    section_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Borra una sección del esquema."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    if not memoria.delete_section(licitacion_id, current_user.id, section_id, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sección no encontrada")


# ── Propuesta (redacción) ────────────────────────────────────────────────────

@router.post("/{licitacion_id}/memoria/propuesta", response_model=MemoriaPropuestaResponse)
async def draft_propuesta(
    licitacion_id: str,
    body: MemoriaPropuestaRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaPropuestaResponse:
    """Redacta la Memoria completa desde el esquema (síncrono, fan-out por sección)."""
    licitacion = _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    doc = await memoria.draft_propuesta(
        licitacion_id=licitacion_id,
        user_id=current_user.id,
        title=licitacion.title,
        esquema=body.esquema,
        db=db,
        session_factory=SessionLocal,
        tone=body.tono,
    )
    return MemoriaPropuestaResponse(doc_id=doc.id, title=doc.title, markdown=doc.markdown)


# ── Documentos ───────────────────────────────────────────────────────────────

@router.get("/{licitacion_id}/memoria/documents", response_model=List[MemoriaDocumentResponse])
def list_documents(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MemoriaDocumentResponse]:
    """Documentos Markdown persistidos, el más reciente primero."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    docs = memoria.get_documents(licitacion_id, current_user.id, db)
    return [MemoriaDocumentResponse.model_validate(d) for d in docs]


@router.get(
    "/{licitacion_id}/memoria/documents/{doc_id}", response_model=MemoriaDocumentResponse
)
def get_document(
    licitacion_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaDocumentResponse:
    """Un documento concreto (Markdown incluido)."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    doc = memoria.get_document_by_id(doc_id, licitacion_id, current_user.id, db)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")
    return MemoriaDocumentResponse.model_validate(doc)


@router.patch(
    "/{licitacion_id}/memoria/documents/{doc_id}", response_model=MemoriaDocumentResponse
)
def patch_document(
    licitacion_id: str,
    doc_id: str,
    body: MemoriaDocumentPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaDocumentResponse:
    """Edición manual de título/Markdown (autosave del editor)."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    updated = memoria.update_document(
        doc_id=doc_id,
        licitacion_id=licitacion_id,
        user_id=current_user.id,
        title=body.title,
        markdown=body.markdown,
        db=db,
        session_factory=SessionLocal,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")
    return MemoriaDocumentResponse.model_validate(updated)


@router.post(
    "/{licitacion_id}/memoria/documents/{doc_id}/coherencia",
    response_model=MemoriaCoherenciaResponse,
)
async def review_coherence(
    licitacion_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaCoherenciaResponse:
    """Revisión de coherencia del borrador completo (spec-MP §4): lista de
    incidencias (contradicciones, [COMPLETAR: …] pendientes, afirmaciones a
    verificar). No reescribe el documento."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    doc = memoria.get_document_by_id(doc_id, licitacion_id, current_user.id, db)
    if doc is None or not doc.markdown:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")
    issues = await memoria.review_coherence(licitacion_id, doc.markdown)
    return MemoriaCoherenciaResponse(doc_id=doc_id, incidencias=issues)


# ── Chat de refinado ─────────────────────────────────────────────────────────

@router.post("/{licitacion_id}/memoria/chat", response_model=MemoriaDocChatResponse)
async def refine_via_chat(
    licitacion_id: str,
    body: MemoriaDocChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoriaDocChatResponse:
    """Edita el Markdown según la petición del usuario (histórico + grounding)."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    edited, reply = await memoria.refine_document(
        doc_id=body.doc_id,
        licitacion_id=licitacion_id,
        user_id=current_user.id,
        current_markdown=body.markdown,
        instruction=body.message,
        db=db,
        session_factory=SessionLocal,
    )
    return MemoriaDocChatResponse(markdown=edited, texto_chat=reply)


@router.get("/{licitacion_id}/memoria/chat", response_model=List[MemoriaChatMessageResponse])
def chat_history(
    licitacion_id: str,
    doc_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MemoriaChatMessageResponse]:
    """Historial del chat de refinado (filtrable por documento)."""
    _owned_licitacion_or_404(licitacion_id, current_user.id, db)
    rows = memoria.list_chat_history(licitacion_id, current_user.id, db, doc_id=doc_id)
    return [MemoriaChatMessageResponse.model_validate(r) for r in rows]


# ── Export (PDF / DOCX) ──────────────────────────────────────────────────────
# Adaptador HTTP del servicio de render (services/memoria_export.py, tarea 5.6 ♻).
# El export NO forma parte de la demo (spec-demo-minimal §2 DM5).

_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.post("/{licitacion_id}/memoria/export")
def export_document(
    licitacion_id: str,
    body: MemoriaExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Exporta el Markdown (del body o el persistido) a PDF o DOCX (5.6)."""
    licitacion = _owned_licitacion_or_404(licitacion_id, current_user.id, db)

    markdown = body.markdown
    document_title = ""
    if markdown is None and body.doc_id:
        doc = memoria.get_document_by_id(body.doc_id, licitacion_id, current_user.id, db)
        if doc:
            markdown = doc.markdown
            document_title = doc.title
    if not markdown:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No hay documento que exportar."
        )

    from app.services.memoria_export import (
        ExportOptions,
        render_markdown_docx,
        render_markdown_pdf,
    )

    company = (
        db.query(CompanyProfile)
        .filter(
            CompanyProfile.created_by == current_user.id,
            CompanyProfile.is_default == True,  # noqa: E712
        )
        .first()
    )
    now = datetime.now()
    variables = {
        "current_date": now.strftime("%d/%m/%Y"),
        "current_year": str(now.year),
        "company_name": company.name if company else "",
        "tender_title": licitacion.title,
        "document_title": document_title,
        "user_name": current_user.full_name or current_user.email,
        "user_email": current_user.email,
    }
    options = ExportOptions(
        # Cabecera por defecto: nombre de empresa del perfil (5.6). El componente
        # document-header del propio documento, si existe, manda sobre esto.
        header_text=body.header_text if body.header_text is not None
        else (company.name if company else None),
        footer_text=body.footer_text,
        logo_data_uri=body.logo_data_uri,
        include_toc=body.include_toc,
    )

    if body.format == "docx":
        docx_bytes = render_markdown_docx(markdown, variables=variables, options=options)
        return Response(
            content=docx_bytes,
            media_type=_DOCX_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="memoria_{licitacion_id[:8]}.docx"'
            },
        )

    try:
        pdf_bytes = render_markdown_pdf(markdown, variables=variables, options=options)
    except OSError as e:
        # WeasyPrint requiere libs nativas (Pango); pueden faltar en dev Windows.
        from app.core.logging import get_logger

        get_logger(__name__).error(f"Export a PDF falló (¿libs nativas?): {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Export a PDF no disponible: faltan librerías nativas de WeasyPrint "
                "(GTK/Pango). Ver docs de instalación."
            ),
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="memoria_{licitacion_id[:8]}.pdf"'
        },
    )
