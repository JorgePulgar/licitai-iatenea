"""
Endpoints de plantillas/memorias de referencia (CompanyTemplate).

Rutas bajo /api/v1/templates. Cada plantilla pertenece a un único usuario y se usa
después como contexto al generar Memorias Técnicas.

Flujo: subir → extraer texto → resumen profundo → persistir. Ver
`app/services/templates.py` para los detalles del agente de síntesis.
"""

from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.logging import get_logger
from app.db.database import get_db
from app.models.domain import User
from app.models.schemas import CompanyTemplateResponse, CompanyTemplateUpdate
from app.services import templates as templates_service

logger = get_logger(__name__)
router = APIRouter()


def _to_response(template) -> CompanyTemplateResponse:
    return CompanyTemplateResponse(
        id=template.id,
        filename=template.filename,
        title=template.title,
        description=template.description,
        mime_type=template.mime_type,
        file_size=template.file_size,
        page_count=template.page_count,
        has_summary=bool(template.summary),
        created_at=template.created_at,
    )


@router.get("/", response_model=List[CompanyTemplateResponse])
def list_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[CompanyTemplateResponse]:
    """Plantillas del usuario, ordenadas por fecha (más recientes primero)."""
    rows = templates_service.list_templates(current_user.id, db)
    return [_to_response(t) for t in rows]


@router.post(
    "/",
    response_model=CompanyTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_template(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyTemplateResponse:
    """
    Sube una plantilla (PDF o DOCX), extrae su texto y genera la síntesis profunda.

    El proceso es síncrono porque el usuario espera ver la plantilla disponible
    al volver a la pantalla. Para PDFs grandes esto puede tardar 10–30 s.
    """
    file_bytes = await file.read()
    mime_type = file.content_type or "application/octet-stream"

    try:
        template = await templates_service.create_template_from_upload(
            user_id=current_user.id,
            file_bytes=file_bytes,
            filename=file.filename or "documento.pdf",
            mime_type=mime_type,
            title=title,
            description=description,
            db=db,
        )
    except templates_service.TemplateProcessingError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error uploading template: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error procesando la plantilla.",
        )

    return _to_response(template)


@router.patch("/{template_id}", response_model=CompanyTemplateResponse)
def update_template(
    template_id: str,
    body: CompanyTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyTemplateResponse:
    """Edita metadatos visibles (título, descripción). No regenera el resumen."""
    template = templates_service.update_template_metadata(
        template_id=template_id,
        user_id=current_user.id,
        title=body.title,
        description=body.description,
        db=db,
    )
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")
    return _to_response(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Borra la plantilla (DB + blob). 404 si no existe o no pertenece al usuario."""
    deleted = templates_service.delete_template(template_id, current_user.id, db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")
    return None
