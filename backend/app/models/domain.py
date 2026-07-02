import enum
from datetime import date, datetime, timezone
from typing import List, Optional
from sqlalchemy import Boolean, Date, String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class DocumentType(str, enum.Enum):
    pcap = "pcap"
    ppt = "ppt"
    anexo = "anexo"


class PliegoStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    indexed = "indexed"
    error = "error"


class LicitacionStatus(str, enum.Enum):
    processing = "processing"
    indexed = "indexed"
    partial_error = "partial_error"
    error = "error"


class LicitacionEstado(str, enum.Enum):
    """Estado comercial/de workflow de la licitación (distinto del estado de pipeline `status`)."""
    elaborando = "elaborando"
    revision_comercial = "revision_comercial"
    entregada = "entregada"
    resuelta = "resuelta"  # terminal; `resultado` indica Ganada (True) / Perdida (False)


class Licitacion(Base):
    __tablename__ = "licitaciones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column("titulo", String(512), nullable=False)
    # `status` = estado del pipeline (processing/indexed/error). NO confundir con `estado`.
    status: Mapped[str] = mapped_column(String(20), default="processing", nullable=False)
    # `estado` = estado comercial editable por el usuario. Arranca en "elaborando".
    estado: Mapped[str] = mapped_column(String(30), default="elaborando", nullable=False)
    # `resultado` solo aplica cuando estado == "resuelta": True=Ganada, False=Perdida, None=pendiente.
    resultado: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Fecha límite de presentación de la oferta (editable).
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    documents: Mapped[List["Pliego"]] = relationship(
        "Pliego", back_populates="licitacion", cascade="all, delete-orphan"
    )
    summary: Mapped[Optional["LicitacionSummary"]] = relationship(
        "LicitacionSummary", back_populates="licitacion", cascade="all, delete-orphan", uselist=False
    )


class Pliego(Base):
    __tablename__ = "pliegos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    licitacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licitaciones.id"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column("tipo_pliego", String(50), nullable=False)  # PCAP | PPT | ANEXO
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # Título extraído de la primera página del PDF (rol "title"/"sectionHeading" de Azure DI,
    # o fallback LLM sobre el texto de la página 1). 512 porque los títulos de PPT/PCAP
    # administrativos pueden superar los 280 caracteres. Nullable: pliegos antiguos o
    # procesados con el fallback pypdf no lo tienen → la UI muestra el filename.
    doc_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    blob_url: Mapped[str] = mapped_column(String, nullable=False)
    blob_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="uploaded", nullable=False)
    ocr_quality_score: Mapped[float | None] = mapped_column(nullable=True)
    low_quality_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    licitacion: Mapped["Licitacion"] = relationship("Licitacion", back_populates="documents")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LicitacionSummary(Base):
    __tablename__ = "licitacion_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    licitacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    licitacion: Mapped["Licitacion"] = relationship("Licitacion", back_populates="summary")


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    licitacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Hilo de conversación (chat de consultas). Agrupa los turnos de una misma sesión;
    # NULL en filas antiguas anteriores a las sesiones (se tratan como "sesión heredada").
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_ids: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON: full citation objects
    chunk_scores: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON: relevance scores
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    had_citations: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_unanswerable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sectors: Mapped[str | None] = mapped_column(Text, nullable=True)            # JSON array
    certifications: Mapped[str | None] = mapped_column(Text, nullable=True)     # JSON array
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annual_revenue: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notable_clients: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON array
    solvency_tech: Mapped[str | None] = mapped_column(Text, nullable=True)
    solvency_econ: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CompanyTemplate(Base):
    """
    Plantilla o memoria de referencia subida por la empresa para alimentar la
    redacción de futuras Memorias Técnicas (estilo, estructura, tono).

    `extracted_text` guarda el texto íntegro extraído (OCR/parser). `summary` es la
    síntesis profunda generada por el agente de resumen (estructura, propuesta de
    valor, tono, voz) que se inyecta en el prompt de la Memoria Técnica.
    """

    __tablename__ = "company_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    # user_id sin FK — coherente con memoria_sections/memoria_chat_messages/memoria_documents;
    # `users.id` en este servidor es UNIQUEIDENTIFIER y aquí guardamos su representación
    # como VARCHAR(36). El aislamiento se garantiza por código (filtro por user_id en cada query).
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf", nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blob_url: Mapped[str] = mapped_column(String, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PliegoRequirement(Base):
    __tablename__ = "pliego_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    licitacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    categoria: Mapped[str] = mapped_column(String(50), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    pagina: Mapped[int | None] = mapped_column(Integer, nullable=True)
    documento_origen: Mapped[str] = mapped_column(String(20), nullable=False)
    es_obligatorio: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    licitacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON: full match response
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MemoriaSection(Base):
    """
    Sección del esqueleto de la Memoria Técnica de una licitación.

    Solo estructura, no redacción: el campo ``content`` queda reservado (vacío)
    para que la generación de propuesta de S4 lo rellene sin cambio de esquema.
    Ver docs/ADR/ADR-001-memoria-tecnica-esqueleto.md.
    """

    __tablename__ = "memoria_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    licitacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column("titulo", String(512), nullable=False)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    criterio_adjudicacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_puntos: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # reservado para S4
    sort_order: Mapped[int] = mapped_column("orden", Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed", nullable=False)  # proposed | accepted | edited
    source: Mapped[str] = mapped_column(String(20), default="llm", nullable=False)  # llm | template | pliego | user
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class MemoriaChatMessage(Base):
    """Mensaje del chat de propuesta de secciones de la Memoria Técnica."""

    __tablename__ = "memoria_chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    licitacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # Documento al que pertenece este turno. Permite que cada versión de la Memoria
    # mantenga su propio hilo de chat. Nullable por compatibilidad con turnos antiguos.
    doc_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MemoriaDocument(Base):
    """
    Documento Markdown de la Memoria Técnica redactada (una fila por licitación).

    La estructura (esquema) vive en `memoria_sections`; aquí se guarda la prosa
    redactada y editable por chat. Ver docs/ADR/ADR-002-memoria-tecnica-flujo-completo.md.
    """

    __tablename__ = "memoria_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    licitacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licitaciones.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="Borrador", nullable=False)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
