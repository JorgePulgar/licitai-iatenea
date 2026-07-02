"""
Seed script — creates default dev users in the database.

Run from the backend/ directory:
    python scripts/seed_users.py

Safe to run multiple times: existing users are skipped.
Only intended for ENVIRONMENT=dev.
"""

import sys
import os

# Allow importing from app/ regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from app.core.config import settings

if settings.ENVIRONMENT != "dev":
    print(f"ERROR: ENVIRONMENT is '{settings.ENVIRONMENT}'. Seed script only runs in dev.")
    sys.exit(1)

from sqlalchemy.orm import Session
from app.db.database import engine
from app.db.base import Base
from app.models.domain import User  # noqa: F401 — register models in metadata
from app.core.security import hash_password

# ──────────────────────────────────────────────
# Default dev users
# Change passwords here if needed — these are dev-only credentials.
# ──────────────────────────────────────────────
SEED_USERS = [
    {"email": "jorge@licitai.dev",  "password": "Licitai2026!"},
    {"email": "alvaro@licitai.dev", "password": "Licitai2026!"},
    {"email": "siro@licitai.dev",   "password": "Licitai2026!"},
]


def seed(db: Session) -> None:
    created = 0
    skipped = 0

    for entry in SEED_USERS:
        existing = db.query(User).filter(User.email == entry["email"]).first()
        if existing:
            print(f"  SKIP   {entry['email']} (already exists, id={existing.id})")
            skipped += 1
            continue

        user = User(
            id=str(uuid.uuid4()),
            email=entry["email"],
            password_hash=hash_password(entry["password"]),
            is_active=True,
        )
        db.add(user)
        db.flush()
        print(f"  CREATE {entry['email']} (id={user.id})")
        created += 1

    db.commit()
    print(f"\nDone — {created} created, {skipped} skipped.")


if __name__ == "__main__":
    print("Creating tables (if they don't exist)...")
    Base.metadata.create_all(bind=engine)
    print("Seeding dev users...\n")
    with Session(engine) as db:
        seed(db)
