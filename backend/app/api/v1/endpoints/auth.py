import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.db.database import get_db
from app.models.domain import Licitacion, User
from app.models.schemas import LoginRequest, TokenResponse, UserCreate, UserResponse

logger = get_logger(__name__)

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Autentica al usuario y devuelve un JWT."""
    user = db.query(User).filter(User.email == body.email).first()

    # Mismo mensaje para usuario no encontrado y contraseña incorrecta
    # — evita enumeración de usuarios.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales incorrectas",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if user is None or not verify_password(body.password, user.password_hash):
        raise invalid

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cuenta desactivada",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": user.id})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    """Devuelve el perfil del usuario autenticado."""
    return current_user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, db: Session = Depends(get_db)) -> User:
    """
    Crea un nuevo usuario. Solo disponible en entorno de desarrollo.
    En staging/prod este endpoint devuelve 403.
    """
    if settings.ENVIRONMENT != "dev":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El registro de usuarios está deshabilitado en este entorno",
        )

    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un usuario con ese email",
        )

    user = User(
        id=str(uuid.uuid4()),
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    RGPD right to erasure (LIC-067).
    Permanently deletes the authenticated user's account and all associated data:
    licitaciones, documents (blobs + search index chunks), and query history.
    Returns 204 on success.
    """
    from app.services.indexing import delete_pliego_from_index
    from app.services.ingestion import delete_pliego_blob

    licitaciones = (
        db.query(Licitacion)
        .options(selectinload(Licitacion.documents))
        .filter(Licitacion.user_id == current_user.id)
        .all()
    )

    for licitacion in licitaciones:
        for pliego in licitacion.documents:
            try:
                delete_pliego_from_index(pliego.id)
            except Exception as e:
                logger.error(f"Error deleting search index for pliego {pliego.id}: {e}")
            try:
                delete_pliego_blob(pliego.blob_url)
            except Exception as e:
                logger.error(f"Error deleting blob for pliego {pliego.id}: {e}")
        db.delete(licitacion)

    db.delete(current_user)
    db.commit()

    logger.info(
        f"User {current_user.id} deleted via RGPD right-to-erasure endpoint. "
        f"Licitaciones removed: {len(licitaciones)}."
    )
    return None
