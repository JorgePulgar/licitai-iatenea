"""
Destructive script — drops ALL tables in the database pointed to by DATABASE_URL.

⚠️  The dev DATABASE_URL points at the SHARED Azure SQL server. Running this
    wipes every teammate's data, not just yours. It refuses to run outside
    ENVIRONMENT=dev and requires explicit interactive confirmation.

Run from the backend/ directory:
    python drop_tables.py
"""

import sys
import os

# Allow importing from app/ regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.core.config import settings
from app.db.database import engine
from app.db.base import Base
from app.models import domain  # noqa: F401 — register models in metadata

if settings.ENVIRONMENT != "dev":
    print(f"ERROR: ENVIRONMENT is '{settings.ENVIRONMENT}'. Refusing to drop tables outside dev.")
    sys.exit(1)

target = engine.url.render_as_string(hide_password=True)
print("⚠️  About to DROP ALL TABLES on:")
print(f"    {target}")
print("    This is shared by the whole team. There is no undo.")
answer = input('Type "drop" to confirm: ').strip()
if answer != "drop":
    print("Aborted.")
    sys.exit(0)

Base.metadata.drop_all(bind=engine)
with engine.begin() as conn:
    conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
print("All tables dropped.")
