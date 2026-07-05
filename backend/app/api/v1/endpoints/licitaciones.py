import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user
from app.db.database import SessionLocal, get_db
from app.models.domain import Licitacion, LicitacionSummary, Pliego, User
from app.models.schemas import (
    LICITACION_ESTADOS,
    LicitacionCreateRequest,
    LicitacionResponse,
    LicitacionUpdateRequest,
    MatchResponse,
    PliegoResponse,
    RequirementsListResponse,
    SummaryResponse,
    SasTokenResponse,
)
from app.services.licitacion import create_licitacion as svc_create_licitacion

router = APIRouter()


@router.get("/upload-token", response_model=SasTokenResponse)
def get_upload_token(current_user: User = Depends(get_current_user)):
    """
    Generates a short-lived (1 hour) SAS token allowing the frontend to upload
    files directly to the Azure Blob Storage container.
    """
    from app.core.config import settings
    from azure.storage.blob import generate_container_sas, ContainerSasPermissions
    from datetime import datetime, timedelta, timezone

    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise HTTPException(status_code=500, detail="Azure Storage no está configurado")

    import re
    # Extract AccountName and AccountKey from connection string
    account_match = re.search(r"AccountName=([^;]+)", settings.AZURE_STORAGE_CONNECTION_STRING)
    key_match = re.search(r"AccountKey=([^;]+)", settings.AZURE_STORAGE_CONNECTION_STRING)

    if not account_match or not key_match:
        raise HTTPException(status_code=500, detail="Connection string inválida")

    account_name = account_match.group(1)
    account_key = key_match.group(1)

    sas_token = generate_container_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        account_key=account_key,
        permission=ContainerSasPermissions(write=True, create=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    return SasTokenResponse(
        sas_token=sas_token,
        container=settings.AZURE_STORAGE_CONTAINER_NAME,
        account=account_name
    )

@router.get("/{licitacion_id}/documents/{pliego_id}/view-url")
def get_document_view_url(
    licitacion_id: str,
    pliego_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generates a short-lived read-only SAS URL for viewing a specific document."""
    from app.core.config import settings
    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
    from datetime import timedelta
    from urllib.parse import unquote
    import re

    pliego = (
        db.query(Pliego)
        .filter(Pliego.id == pliego_id, Pliego.licitacion_id == licitacion_id)
        .first()
    )
    if not pliego:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")

    # Verify ownership
    licitacion = (
        db.query(Licitacion)
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")

    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise HTTPException(status_code=500, detail="Azure Storage no está configurado")

    account_match = re.search(r"AccountName=([^;]+)", settings.AZURE_STORAGE_CONNECTION_STRING)
    key_match = re.search(r"AccountKey=([^;]+)", settings.AZURE_STORAGE_CONNECTION_STRING)
    if not account_match or not key_match:
        raise HTTPException(status_code=500, detail="Connection string inválida")

    account_name = account_match.group(1)
    account_key = key_match.group(1)

    # Extract blob name from blob_path
    blob_name = pliego.blob_path
    container = settings.AZURE_STORAGE_CONTAINER_NAME
    if blob_name.startswith(f"{container}/"):
        blob_name = blob_name[len(container) + 1:]
    blob_name = unquote(blob_name)

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    url = f"https://{account_name}.blob.core.windows.net/{container}/{blob_name}?{sas_token}"
    return {"url": url}


def _licitacion_response(licitacion: Licitacion) -> LicitacionResponse:
    return LicitacionResponse(
        id=licitacion.id,
        user_id=licitacion.user_id,
        title=licitacion.title,
        status=licitacion.status,
        estado=licitacion.estado,
        resultado=licitacion.resultado,
        deadline=licitacion.deadline,
        created_at=licitacion.created_at,
        updated_at=licitacion.updated_at,
        documents=[PliegoResponse.model_validate(p) for p in licitacion.documents],
    )


@router.post("/", response_model=LicitacionResponse, status_code=status.HTTP_201_CREATED)
async def create_licitacion(
    body: LicitacionCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates a licitacion from files already uploaded to blob by the frontend.
    Enqueues OCR + indexing for each document in the background.
    Returns immediately with status 'processing'.
    """
    licitacion = svc_create_licitacion(body, current_user.id, db, background_tasks)
    db.refresh(licitacion)
    # Load documents relationship before session closes
    _ = licitacion.documents
    return _licitacion_response(licitacion)


@router.get("/", response_model=List[LicitacionResponse])
def list_licitaciones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 20,
):
    """Lists all licitaciones for the current user, ordered by creation date."""
    licitaciones = (
        db.query(Licitacion)
        .options(selectinload(Licitacion.documents))
        .filter(Licitacion.user_id == current_user.id)
        .order_by(Licitacion.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_licitacion_response(l) for l in licitaciones]


@router.get("/{licitacion_id}", response_model=LicitacionResponse)
def get_licitacion(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    licitacion = (
        db.query(Licitacion)
        .options(selectinload(Licitacion.documents))
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")
    return _licitacion_response(licitacion)


@router.patch("/{licitacion_id}", response_model=LicitacionResponse)
def update_licitacion(
    licitacion_id: str,
    body: LicitacionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Actualiza estado comercial, resultado (Ganada/Perdida) y/o fecha límite de la licitación."""
    licitacion = (
        db.query(Licitacion)
        .options(selectinload(Licitacion.documents))
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")

    # Solo aplica los campos enviados explícitamente (PATCH parcial).
    data = body.model_dump(exclude_unset=True)

    if "estado" in data:
        if data["estado"] not in LICITACION_ESTADOS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Estado inválido. Valores permitidos: {', '.join(LICITACION_ESTADOS)}",
            )
        licitacion.estado = data["estado"]
        # El resultado (Ganada/Perdida) solo tiene sentido en estado 'resuelta'.
        if data["estado"] != "resuelta" and "resultado" not in data:
            licitacion.resultado = None

    if "resultado" in data:
        licitacion.resultado = data["resultado"]

    if "deadline" in data:
        licitacion.deadline = data["deadline"]

    licitacion.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(licitacion)
    _ = licitacion.documents
    return _licitacion_response(licitacion)


@router.delete("/{licitacion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_licitacion(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes a licitacion and all its documents (DB + blobs + search index)."""
    licitacion = (
        db.query(Licitacion)
        .options(selectinload(Licitacion.documents))
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")

    from app.services.indexing import delete_pliego_from_index
    from app.services.ingestion import delete_pliego_blob

    for pliego in licitacion.documents:
        delete_pliego_from_index(pliego.id)
        delete_pliego_blob(pliego.blob_url)

    db.delete(licitacion)
    db.commit()
    return None


@router.get("/{licitacion_id}/summary", response_model=SummaryResponse)
async def get_summary(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SummaryResponse:
    """Returns cached summary if available, otherwise generates via LLM and caches result."""
    licitacion = (
        db.query(Licitacion)
        .options(selectinload(Licitacion.documents))
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")

    if licitacion.status not in ("indexed", "partial_error"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La licitación no está indexada (estado actual: {licitacion.status})",
        )

    cached_row = (
        db.query(LicitacionSummary)
        .filter(LicitacionSummary.licitacion_id == licitacion_id)
        .first()
    )
    if cached_row:
        payload = json.loads(cached_row.payload)
        return SummaryResponse(**payload, cached=True, generated_at=cached_row.generated_at)

    from app.services.summary import generate_summary
    result = await generate_summary(
        licitacion_id=licitacion.id,
        user_id=current_user.id,
        title=licitacion.title,
    )

    now = datetime.now(timezone.utc)
    payload_dict = result.model_dump(exclude={"cached", "generated_at"})
    summary_row = LicitacionSummary(
        id=str(uuid.uuid4()),
        licitacion_id=licitacion_id,
        payload=json.dumps(payload_dict),
        generated_at=now,
    )
    # Use a fresh session — the original may have a stale TCP connection
    # after the long LLM call.
    write_db = SessionLocal()
    try:
        write_db.add(summary_row)
        write_db.commit()
    except Exception:
        write_db.rollback()
        raise
    finally:
        write_db.close()

    result.cached = False
    result.generated_at = now
    return result


@router.get("/{licitacion_id}/requirements", response_model=RequirementsListResponse)
async def get_requirements(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RequirementsListResponse:
    """Returns cached requirements if available, otherwise extracts via LLM and caches."""
    licitacion = (
        db.query(Licitacion)
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")

    if licitacion.status not in ("indexed", "partial_error"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La licitación no está indexada (estado actual: {licitacion.status})",
        )

    from app.services.requirements import extract_requirements
    return await extract_requirements(
        licitacion_id=licitacion.id,
        user_id=current_user.id,
        title=licitacion.title,
        db=db,
        session_factory=SessionLocal,
        page_counts=_page_counts_by_doc_type(db, licitacion.id),
    )


def _page_counts_by_doc_type(db: Session, licitacion_id: str) -> dict[str, int]:
    """document_type (lower) → nº máximo de páginas conocido. Para validar que las
    páginas citadas por el LLM existen en el documento origen (5.5)."""
    counts: dict[str, int] = {}
    rows = (
        db.query(Pliego.document_type, Pliego.page_count)
        .filter(Pliego.licitacion_id == licitacion_id, Pliego.page_count.isnot(None))
        .all()
    )
    for doc_type, page_count in rows:
        key = (doc_type or "").lower()
        counts[key] = max(counts.get(key, 0), page_count)
    return counts


@router.post("/{licitacion_id}/requirements/regenerate", response_model=RequirementsListResponse)
async def regenerate_requirements(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RequirementsListResponse:
    """Invalida la cache de requisitos y los vuelve a extraer (5.5). Útil cuando los
    documentos han cambiado (reindexado) o la extracción anterior fue pobre."""
    licitacion = (
        db.query(Licitacion)
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")

    if licitacion.status not in ("indexed", "partial_error"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La licitación no está indexada (estado actual: {licitacion.status})",
        )

    from app.services.requirements import extract_requirements, invalidate_requirements
    invalidate_requirements(licitacion.id, db)
    return await extract_requirements(
        licitacion_id=licitacion.id,
        user_id=current_user.id,
        title=licitacion.title,
        db=db,
        session_factory=SessionLocal,
        page_counts=_page_counts_by_doc_type(db, licitacion.id),
    )


@router.get("/{licitacion_id}/match", response_model=MatchResponse)
def get_cached_match(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MatchResponse:
    """Returns cached match result if available and still valid (profile hash matches). 404 otherwise."""
    licitacion = (
        db.query(Licitacion)
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")

    from app.models.domain import CompanyProfile, MatchResult
    profile = (
        db.query(CompanyProfile)
        .filter(CompanyProfile.created_by == current_user.id, CompanyProfile.is_default == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay perfil de empresa configurado.",
        )

    from app.services.match import compute_profile_hash
    current_hash = compute_profile_hash(profile)

    cached = (
        db.query(MatchResult)
        .filter(
            MatchResult.licitacion_id == licitacion_id,
            MatchResult.profile_id == profile.id,
            MatchResult.profile_hash == current_hash,
        )
        .first()
    )
    if not cached:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay resultado de match cacheado para esta licitación.",
        )

    payload = json.loads(cached.payload)
    return MatchResponse(**payload, cached=True)


@router.post("/{licitacion_id}/match", response_model=MatchResponse)
async def match_score(
    licitacion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MatchResponse:
    """Calculates fit score using saved company profile + extracted requirements. Cached with profile hash invalidation."""
    licitacion = (
        db.query(Licitacion)
        .filter(Licitacion.id == licitacion_id, Licitacion.user_id == current_user.id)
        .first()
    )
    if not licitacion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada")

    if licitacion.status not in ("indexed", "partial_error"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La licitación no está indexada (estado actual: {licitacion.status})",
        )

    from app.models.domain import CompanyProfile, MatchResult
    profile = (
        db.query(CompanyProfile)
        .filter(CompanyProfile.created_by == current_user.id, CompanyProfile.is_default == True)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se ha configurado un perfil de empresa. Ve a Ajustes > Perfil de empresa.",
        )

    from app.services.match import calculate_match, compute_profile_hash
    current_hash = compute_profile_hash(profile)

    # Check cache
    cached = (
        db.query(MatchResult)
        .filter(
            MatchResult.licitacion_id == licitacion_id,
            MatchResult.profile_id == profile.id,
            MatchResult.profile_hash == current_hash,
        )
        .first()
    )
    if cached:
        payload = json.loads(cached.payload)
        return MatchResponse(**payload, cached=True)

    # Ensure requirements are extracted first
    from app.services.requirements import extract_requirements
    reqs_result = await extract_requirements(
        licitacion_id=licitacion.id,
        user_id=current_user.id,
        title=licitacion.title,
        db=db,
        session_factory=SessionLocal,
        page_counts=_page_counts_by_doc_type(db, licitacion.id),
    )

    result = await calculate_match(
        licitacion_id=licitacion.id,
        user_id=current_user.id,
        title=licitacion.title,
        profile=profile,
        requirements=reqs_result.requirements,
    )

    # Cache result with a fresh session — the original may have a stale
    # TCP connection after the long search + LLM calls.
    now = datetime.now(timezone.utc)
    write_db = SessionLocal()
    try:
        # Delete old cache for this licitacion+profile
        write_db.query(MatchResult).filter(
            MatchResult.licitacion_id == licitacion_id,
            MatchResult.profile_id == profile.id,
        ).delete()

        payload_dict = result.model_dump(exclude={"cached"})
        match_row = MatchResult(
            id=str(uuid.uuid4()),
            licitacion_id=licitacion_id,
            profile_id=profile.id,
            profile_hash=current_hash,
            payload=json.dumps(payload_dict, default=str),
            generated_at=now,
        )
        write_db.add(match_row)
        write_db.commit()
    except Exception:
        write_db.rollback()
        raise
    finally:
        write_db.close()

    result.cached = False
    return result
