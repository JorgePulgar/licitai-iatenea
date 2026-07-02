"""LIC-054 — auth endpoint tests: login, /me, /register."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.db.base import Base
from app.db.database import get_db
from app.models.domain import User
from app.core.security import hash_password, create_access_token
from app.core.config import settings
from app.main import app

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_auth.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def clean_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_user(db):
    user = User(
        id="user-test-1",
        email="test@example.com",
        password_hash=hash_password("Password123!"),
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: (yield db)
    return TestClient(app)


# ── login ─────────────────────────────────────────────────────────────────────

def test_login_valid_credentials(client, test_user):
    response = client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "Password123!",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password_returns_401(client, test_user):
    response = client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "wrong-password",
    })
    assert response.status_code == 401


def test_login_unknown_email_returns_401(client, db):
    response = client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com",
        "password": "Password123!",
    })
    assert response.status_code == 401


# ── /me ───────────────────────────────────────────────────────────────────────

def test_me_with_valid_token(client, test_user):
    token = create_access_token({"sub": test_user.id})
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"


def test_me_with_malformed_token_returns_401(client, test_user):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert response.status_code == 401


def test_me_with_expired_token_returns_401(client, test_user):
    from datetime import timedelta
    # Create token that expired 1 hour ago
    token = create_access_token({"sub": test_user.id}, expires_delta=timedelta(hours=-1))
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# ── /register ─────────────────────────────────────────────────────────────────

def test_register_creates_user_in_dev(client, db):
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "dev"
    try:
        response = client.post("/api/v1/auth/register", json={
            "email": "newuser@example.com",
            "password": "ValidPass123!",
        })
        assert response.status_code == 201
        assert response.json()["email"] == "newuser@example.com"
    finally:
        settings.ENVIRONMENT = original_env


def test_register_duplicate_email_returns_409(client, test_user):
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "dev"
    try:
        response = client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "ValidPass123!",
        })
        assert response.status_code == 409
    finally:
        settings.ENVIRONMENT = original_env


def test_register_short_password_returns_422(client, db):
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "dev"
    try:
        response = client.post("/api/v1/auth/register", json={
            "email": "short@example.com",
            "password": "short",
        })
        assert response.status_code == 422
    finally:
        settings.ENVIRONMENT = original_env


def test_register_forbidden_in_non_dev(client, db):
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "prod"
    try:
        response = client.post("/api/v1/auth/register", json={
            "email": "blocked@example.com",
            "password": "ValidPass123!",
        })
        assert response.status_code == 403
    finally:
        settings.ENVIRONMENT = original_env
