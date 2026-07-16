"""
Endpoint del perfil de empresa — reescrito desde spec funcional (DM6, spec-demo-minimal §2).

Alcance DM6 (3.1 parcial): perfil ÚNICO por usuario, aislado por `created_by`.
Sin modelo de organizaciones ni cambios de esquema: las columnas org llegan
intactas con spec-3.1 (el perfil pasará entonces a ser org-compartido, con
varios perfiles nombrados y un único `is_default` por org).

Contrato:
  GET  /api/v1/perfil/  → perfil por defecto del usuario; 404 si aún no existe.
  PUT  /api/v1/perfil/  → upsert del perfil (crea si no existe, si no actualiza).

Las listas (sectores, certificaciones, clientes) se guardan como JSON en
columnas Text y se (de)serializan aquí; el resto de campos son escalares.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.database import get_db
from app.models.domain import CompanyProfile, User
from app.models.schemas import CompanyProfileResponse, CompanyProfileUpdate

router = APIRouter()

# Campos lista ↔ columna JSON (mismo nombre en schema y modelo).
_LIST_FIELDS = ("sectors", "certifications", "notable_clients")
# Campos escalares que se copian tal cual del schema al modelo.
_SCALAR_FIELDS = (
    "name",
    "description",
    "employee_count",
    "annual_revenue",
    "solvency_tech",
    "solvency_econ",
)


def _own_profile(db: Session, user_id: str) -> CompanyProfile | None:
    """Perfil del usuario autenticado (único por usuario en el alcance DM6)."""
    return (
        db.query(CompanyProfile)
        .filter(CompanyProfile.created_by == user_id)
        .first()
    )


def _apply(profile: CompanyProfile, body: CompanyProfileUpdate) -> None:
    """Vuelca el schema sobre el modelo (listas serializadas a JSON, o NULL)."""
    for field in _SCALAR_FIELDS:
        setattr(profile, field, getattr(body, field))
    for field in _LIST_FIELDS:
        values = getattr(body, field)
        setattr(profile, field, json.dumps(values) if values else None)
    profile.updated_at = datetime.now(timezone.utc)


def _serialize(profile: CompanyProfile) -> CompanyProfileResponse:
    """Modelo → respuesta (columnas JSON deserializadas a listas)."""
    def as_list(raw: str | None) -> list[str]:
        return json.loads(raw) if raw else []

    return CompanyProfileResponse(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        sectors=as_list(profile.sectors),
        certifications=as_list(profile.certifications),
        employee_count=profile.employee_count,
        annual_revenue=profile.annual_revenue,
        notable_clients=as_list(profile.notable_clients),
        solvency_tech=profile.solvency_tech,
        solvency_econ=profile.solvency_econ,
        is_default=profile.is_default,
        updated_at=profile.updated_at,
    )


@router.get("/", response_model=CompanyProfileResponse)
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyProfileResponse:
    """Perfil de empresa del usuario autenticado."""
    profile = _own_profile(db, current_user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Perfil de empresa no encontrado",
        )
    return _serialize(profile)


@router.put("/", response_model=CompanyProfileResponse)
def upsert_profile(
    body: CompanyProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyProfileResponse:
    """Crea el perfil si no existe; si existe, lo actualiza íntegro."""
    profile = _own_profile(db, current_user.id)
    if profile is None:
        profile = CompanyProfile(
            id=str(uuid.uuid4()),
            is_default=True,
            created_by=current_user.id,
            created_at=datetime.now(timezone.utc),
        )
        _apply(profile, body)
        db.add(profile)
    else:
        _apply(profile, body)

    db.commit()
    db.refresh(profile)
    return _serialize(profile)
