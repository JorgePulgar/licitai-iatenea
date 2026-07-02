import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import setup_logging, set_log_context
from app.core.telemetry import setup_telemetry
from app.models import domain  # noqa: F401
from app.api.v1.endpoints import auth, licitaciones, query, perfil, memoria, templates, audit
from app.services.indexing import create_index_if_not_exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(level=settings.LOG_LEVEL)
    setup_telemetry()
    create_index_if_not_exists()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="Plataforma RAG para análisis de licitaciones públicas españolas.",
    lifespan=lifespan
)


@app.middleware("http")
async def inject_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    set_log_context(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(licitaciones.router, prefix=f"{settings.API_V1_STR}/licitaciones", tags=["licitaciones"])
app.include_router(memoria.router, prefix=f"{settings.API_V1_STR}/licitaciones", tags=["memoria"])
app.include_router(query.router, prefix=f"{settings.API_V1_STR}/query", tags=["query"])
app.include_router(perfil.router, prefix=f"{settings.API_V1_STR}/perfil", tags=["perfil"])
app.include_router(templates.router, prefix=f"{settings.API_V1_STR}/templates", tags=["templates"])
app.include_router(audit.router, prefix=f"{settings.API_V1_STR}/system", tags=["audit"])


@app.get("/health", tags=["status"])
def health_check():
    return {"status": "ok", "version": settings.VERSION}
