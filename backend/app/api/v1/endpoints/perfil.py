import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.database import get_db
from app.models.domain import CompanyProfile, User
from app.models.schemas import CompanyProfileCreate, CompanyProfileResponse, CompanyProfileUpdate

router = APIRouter()

@router.get("/", response_model=CompanyProfileResponse)
def get_company_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyProfileResponse:
    """Gets the user's default company profile."""
    profile = db.query(CompanyProfile).filter(CompanyProfile.created_by == current_user.id).first()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Perfil de empresa no encontrado",
        )
        
    return _to_response(profile)

@router.put("/", response_model=CompanyProfileResponse)
def update_company_profile(
    body: CompanyProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyProfileResponse:
    """Creates or updates the user's default company profile."""
    profile = db.query(CompanyProfile).filter(CompanyProfile.created_by == current_user.id).first()
    
    sectors_json = json.dumps(body.sectors) if body.sectors else None
    certs_json = json.dumps(body.certifications) if body.certifications else None
    clients_json = json.dumps(body.notable_clients) if body.notable_clients else None
    
    if not profile:
        profile = CompanyProfile(
            id=str(uuid.uuid4()),
            name=body.name,
            description=body.description,
            sectors=sectors_json,
            certifications=certs_json,
            employee_count=body.employee_count,
            annual_revenue=body.annual_revenue,
            notable_clients=clients_json,
            solvency_tech=body.solvency_tech,
            solvency_econ=body.solvency_econ,
            is_default=True,
            created_by=current_user.id,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(profile)
    else:
        profile.name = body.name
        profile.description = body.description
        profile.sectors = sectors_json
        profile.certifications = certs_json
        profile.employee_count = body.employee_count
        profile.annual_revenue = body.annual_revenue
        profile.notable_clients = clients_json
        profile.solvency_tech = body.solvency_tech
        profile.solvency_econ = body.solvency_econ
        profile.updated_at = datetime.now(timezone.utc)
        
    db.commit()
    db.refresh(profile)
    return _to_response(profile)

def _to_response(profile: CompanyProfile) -> CompanyProfileResponse:
    sectors = json.loads(profile.sectors) if profile.sectors else []
    certifications = json.loads(profile.certifications) if profile.certifications else []
    notable_clients = json.loads(profile.notable_clients) if profile.notable_clients else []
    
    return CompanyProfileResponse(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        sectors=sectors,
        certifications=certifications,
        employee_count=profile.employee_count,
        annual_revenue=profile.annual_revenue,
        notable_clients=notable_clients,
        solvency_tech=profile.solvency_tech,
        solvency_econ=profile.solvency_econ,
        is_default=profile.is_default,
        updated_at=profile.updated_at,
    )
