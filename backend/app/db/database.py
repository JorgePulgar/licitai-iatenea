import struct
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.db.base import Base  # noqa: F401 — re-exportado para que Alembic env.py lo importe desde aquí

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
)

# Azure AD token authentication: inject access token into pyodbc connections.
# Required because the ODBC driver on macOS does not support
# Authentication=ActiveDirectoryDefault natively.
if getattr(settings, "_azure_ad_auth", False):
    from azure.identity import DefaultAzureCredential

    _credential = DefaultAzureCredential()
    _SQL_TOKEN_URL = "https://database.windows.net/.default"

    @event.listens_for(engine, "do_connect")
    def _provide_azure_ad_token(dialect, conn_rec, cargs, cparams):
        token = _credential.get_token(_SQL_TOKEN_URL).token
        # pyodbc expects the token as a bytes struct: (token_bytes, length)
        token_bytes = token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
        cparams["attrs_before"] = {
            # SQL_COPT_SS_ACCESS_TOKEN = 1256
            1256: token_struct,
        }


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """
    Dependencia de FastAPI que provee una sesión de BD por request.
    Usa el patrón try/finally para garantizar que la sesión siempre se cierra,
    incluso si se lanza una excepción dentro del endpoint.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
