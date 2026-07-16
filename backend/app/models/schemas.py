from enum import Enum
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from datetime import date, datetime
from typing import List, Optional


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserResponse(BaseModel):
    id: str
    email: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Document types ─────────────────────────────────────────────────────────────

class DocumentType(str, Enum):
    pcap = "pcap"
    ppt = "ppt"
    anexo = "anexo"


# ── Licitacion ─────────────────────────────────────────────────────────────────

class DocumentUploadInfo(BaseModel):
    """Metadata for a file already uploaded to blob storage by the frontend."""
    blob_url: str
    filename: str
    size_bytes: int


class SasTokenResponse(BaseModel):
    sas_token: str
    container: str
    account: str


class LicitacionCreateRequest(BaseModel):
    title: str
    pcap: DocumentUploadInfo
    ppt: Optional[DocumentUploadInfo] = None
    anexos: List[DocumentUploadInfo] = Field(default_factory=list)
    deadline: Optional[date] = None  # fecha límite opcional fijada al crear


# Estados comerciales válidos (ver LicitacionEstado en domain.py).
LICITACION_ESTADOS = ("elaborando", "revision_comercial", "entregada", "resuelta")


class LicitacionUpdateRequest(BaseModel):
    """PATCH parcial: estado comercial, resultado (Ganada/Perdida) y fecha límite."""
    estado: Optional[str] = None
    resultado: Optional[bool] = None
    deadline: Optional[date] = None


class PliegoResponse(BaseModel):
    id: str
    licitacion_id: str
    document_type: str
    filename: str
    doc_title: Optional[str] = None
    blob_url: str
    size_bytes: int
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    status: str
    ocr_quality_score: Optional[float] = None
    low_quality_flag: bool = False

    model_config = ConfigDict(from_attributes=True)


class LicitacionResponse(BaseModel):
    id: str
    user_id: str
    title: str
    status: str
    estado: str = "elaborando"
    resultado: Optional[bool] = None
    deadline: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    documents: List[PliegoResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ── OCR / Indexing ─────────────────────────────────────────────────────────────

class Chunk(BaseModel):
    """Text fragment extracted from a document, ready to be embedded and indexed."""
    chunk_id: str
    pliego_id: str
    licitacion_id: str
    user_id: str
    document_type: str  # pcap | ppt | anexo
    filename: str
    content: str
    page_number: Optional[int] = None
    bounding_box: Optional[List[float]] = None  # [x1, y1, x2, y2, x3, y3, x4, y4]
    embedding: Optional[List[float]] = None
    # Ordinal del chunk dentro del pliego (0,1,2…), en orden de lectura. Habilita la
    # expansión por vecinos en la búsqueda (recuperar seq±1). None en chunks heredados
    # indexados antes de esta funcionalidad → la expansión los ignora con elegancia.
    seq: Optional[int] = None
    # Título de la sección (role="sectionHeading" de Azure DI) a la que pertenece el
    # chunk. Se antepone al contenido para mantener pureza semántica del embedding y
    # contexto de cita. None cuando no se detectan secciones (fallback por página).
    section_heading: Optional[str] = None


class IndexResult(BaseModel):
    pliego_id: str
    chunks_indexed: int
    pages_count: int = 0
    status: str


# ── Query / RAG ────────────────────────────────────────────────────────────────

class Citation(BaseModel):
    content: str
    page_number: Optional[int] = None
    pliego_id: str
    licitacion_id: str
    filename: str
    document_type: str


class QueryRequest(BaseModel):
    question: str
    licitacion_id: str
    document_type: Optional[str] = None  # optional filter: pcap | ppt | anexo
    # Hilo de la conversación. El cliente lo genera al abrir "Nueva conversación" y lo
    # envía en cada turno: la memoria se acota a esta sesión, así hilos distintos no se
    # contaminan. Si es None, se cae al comportamiento heredado (últimos turnos de la
    # licitación) por compatibilidad.
    session_id: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    # Telemetría interna del LLM (tarea 1.7). exclude=True: no se serializa nunca
    # al cliente; el endpoint la persiste en la fila `Query` para el reporting de uso.
    tokens_prompt: Optional[int] = Field(default=None, exclude=True)
    tokens_completion: Optional[int] = Field(default=None, exclude=True)


class QueryHistoryItem(BaseModel):
    id: str
    question: str
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    created_at: datetime
    session_id: Optional[str] = None


class QuerySession(BaseModel):
    """Un hilo de conversación del chat de consultas (agrupa turnos por session_id)."""
    session_id: str
    title: str                  # primera pregunta del hilo, como rótulo
    message_count: int          # nº de turnos (pregunta+respuesta cuentan como 1)
    created_at: datetime        # primer turno del hilo
    updated_at: datetime        # último turno del hilo


# ── Summary ────────────────────────────────────────────────────────────────────

class SummaryResponse(BaseModel):
    licitacion_id: str
    objeto: str
    presupuesto: Optional[str] = None
    plazo_ejecucion: Optional[str] = None
    solvencia_tecnica: List[str] = Field(default_factory=list)
    solvencia_economica: List[str] = Field(default_factory=list)
    criterios_adjudicacion: List[str] = Field(default_factory=list)
    plazos_clave: List[str] = Field(default_factory=list)
    resumen: str
    cached: bool = False
    generated_at: Optional[datetime] = None


# ── Company Profile ────────────────────────────────────────────────────────────

class CompanyProfileUpdate(BaseModel):
    name: str
    description: Optional[str] = None
    sectors: Optional[List[str]] = None
    certifications: Optional[List[str]] = None
    employee_count: Optional[int] = None
    annual_revenue: Optional[str] = None
    notable_clients: Optional[List[str]] = None
    solvency_tech: Optional[str] = None
    solvency_econ: Optional[str] = None


CompanyProfileCreate = CompanyProfileUpdate  # alias for clarity in endpoint


class CompanyProfileResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    sectors: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    employee_count: Optional[int] = None
    annual_revenue: Optional[str] = None
    notable_clients: List[str] = Field(default_factory=list)
    solvency_tech: Optional[str] = None
    solvency_econ: Optional[str] = None
    is_default: bool = True
    updated_at: datetime


# ── Requirements ──────────────────────────────────────────────────────────────

class RequirementResponse(BaseModel):
    id: str
    categoria: str
    descripcion: str
    pagina: Optional[int] = None
    documento_origen: str
    es_obligatorio: bool


class RequirementsListResponse(BaseModel):
    licitacion_id: str
    requirements: List[RequirementResponse] = Field(default_factory=list)
    cached: bool = False
    generated_at: Optional[datetime] = None


# ── Match Score ────────────────────────────────────────────────────────────────

class MatchCriterion(BaseModel):
    criterio: str
    puntuacion: int = Field(ge=0, le=10)
    justificacion: str


class RequirementMatch(BaseModel):
    requisito_id: str
    descripcion: str
    categoria: str
    estado: str  # "cumplido" | "no_cumplido" | "indeterminado"
    justificacion: str
    pagina: Optional[int] = None
    documento_origen: Optional[str] = None


class MatchResponse(BaseModel):
    licitacion_id: str
    puntuacion_total: int = Field(ge=0, le=100)
    nivel_encaje: str  # "Alto" | "Medio" | "Bajo"
    resumen: str
    desglose: List[MatchCriterion] = Field(default_factory=list)
    requisitos_evaluados: List[RequirementMatch] = Field(default_factory=list)
    cached: bool = False


# ── Company Templates (Referencias) ─────────────────────────────────────────────

class CompanyTemplateResponse(BaseModel):
    """Plantilla/memoria de referencia subida por la empresa."""
    id: str
    filename: str
    title: Optional[str] = None
    description: Optional[str] = None
    mime_type: str = "application/pdf"
    file_size: Optional[int] = None
    page_count: Optional[int] = None
    has_summary: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CompanyTemplateUpdate(BaseModel):
    """Edición de metadatos (no del contenido)."""
    title: Optional[str] = None
    description: Optional[str] = None

# ── Memoria Técnica (esqueleto) ─────────────────────────────────────────────
# Esqueleto de la Memoria Técnica a presentar. Solo estructura, no redacción:
# el contenido de cada sección lo rellena la generación de propuesta de S4.
# Ver docs/ADR/ADR-001-memoria-tecnica-esqueleto.md.

class MemoriaSectionDraft(BaseModel):
    """Sección propuesta por el LLM, aún sin persistir."""
    title: str
    description: Optional[str] = None
    criterio_adjudicacion: Optional[str] = None
    max_puntos: Optional[float] = None
    page_budget: Optional[int] = None
    sort_order: int = 0


class MemoriaSectionResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    criterio_adjudicacion: Optional[str] = None
    max_puntos: Optional[float] = None
    page_budget: Optional[int] = None
    sort_order: int
    status: str          # proposed | accepted | edited
    source: str          # llm | template | pliego | user
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemoriaChatMessageResponse(BaseModel):
    id: str
    role: str            # user | assistant
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemoriaSectionsSaveRequest(BaseModel):
    sections: List[MemoriaSectionDraft] = Field(default_factory=list)


class MemoriaSectionPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    criterio_adjudicacion: Optional[str] = None
    max_puntos: Optional[float] = None
    page_budget: Optional[int] = None
    sort_order: Optional[int] = None
    status: Optional[str] = None


# Flujo completo (ADR-002): esquema → propuesta (Markdown) → chat → export.

# Endpoint 1 — generación de esquema (agente esquema).
# Sin template_ids: las plantillas de referencia (CompanyTemplate) son flujo 3.2b,
# fuera de la ruta de demo (spec-demo-minimal / DM5).
class MemoriaEsquemaRequest(BaseModel):
    message: str = ""


class MemoriaEsquemaResponse(BaseModel):
    reply: str
    esquema: List[MemoriaSectionDraft] = Field(default_factory=list)


# Endpoint 2 — generación de propuesta redactada (agente propuesta).
class MemoriaPropuestaRequest(BaseModel):
    esquema: List[MemoriaSectionDraft] = Field(default_factory=list)
    # Tono de la redacción (spec-memoria-prompts §2): ejecutivo | tecnico | comercial.
    tono: str = "técnico"


class MemoriaPropuestaResponse(BaseModel):
    doc_id: str
    title: str
    markdown: str


# Endpoint 3 — chat de refinado sobre el Markdown (agente conversacional).
class MemoriaDocChatRequest(BaseModel):
    doc_id: str
    markdown: str
    message: str


class MemoriaDocChatResponse(BaseModel):
    markdown: str
    texto_chat: str


# Endpoint 4 — export a PDF.
class MemoriaExportRequest(BaseModel):
    markdown: Optional[str] = None  # si se omite, se usa el documento persistido
    doc_id: Optional[str] = None


class MemoriaDocumentResponse(BaseModel):
    id: str
    licitacion_id: str
    title: str
    markdown: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Edición manual del documento (autosave desde el editor Markdown).
class MemoriaDocumentPatch(BaseModel):
    title: Optional[str] = None
    markdown: Optional[str] = None


# Revisión de coherencia del borrador completo (spec-memoria-prompts §4).
class MemoriaIncidencia(BaseModel):
    tipo: str        # contradiccion | repeticion | requisito_sin_cubrir | completar_pendiente | verificar
    apartado: str
    detalle: str


class MemoriaCoherenciaResponse(BaseModel):
    doc_id: str
    incidencias: List[MemoriaIncidencia] = Field(default_factory=list)


# ── Auditoría del sistema (solo admin, GET /system/audit) ─────────────────────
# Contrato estable: el frontend (services/api.ts) consume estos nombres de campo.

class AuditLicitacionStats(BaseModel):
    total: int
    by_status: dict[str, int]
    created_last_7d: int
    created_last_30d: int


class AuditDocumentStats(BaseModel):
    total_pliegos: int
    total_pages: int
    total_size_mb: float
    by_type: dict[str, int]


class AuditMemoriaStats(BaseModel):
    total_documents: int
    total_chat_messages: int
    total_templates: int


class AuditAIUsageStats(BaseModel):
    total_queries: int
    total_tokens_prompt: int
    total_tokens_completion: int
    total_tokens: int
    avg_latency_ms: Optional[float] = None
    queries_last_7d: int
    queries_last_30d: int


class AuditUserStats(BaseModel):
    total_users: int
    active_users: int


class AuditUserActivity(BaseModel):
    user_id: str
    email: str
    full_name: Optional[str] = None
    licitaciones_count: int
    queries_count: int
    tokens_total: int


class AuditResponse(BaseModel):
    generated_at: datetime
    licitaciones: AuditLicitacionStats
    documents: AuditDocumentStats
    memorias: AuditMemoriaStats
    ai_usage: AuditAIUsageStats
    users: AuditUserStats
    user_activity: List[AuditUserActivity] = Field(default_factory=list)
