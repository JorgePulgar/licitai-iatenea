/** Tipos del contrato de la API (espejo de backend/app/models/schemas.py). */

// ── Auth ────────────────────────────────────────────────────────────────────

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

// ── Licitaciones ────────────────────────────────────────────────────────────

export type PliegoStatus = "uploaded" | "processing" | "indexed" | "error";

export type Pliego = {
  id: string;
  licitacion_id: string;
  document_type: string;
  filename: string;
  doc_title: string | null;
  size_bytes: number;
  uploaded_at: string;
  processed_at: string | null;
  status: PliegoStatus;
  low_quality_flag: boolean;
};

export type LicitacionEstado =
  | "elaborando"
  | "revision_comercial"
  | "entregada"
  | "resuelta";

export type Licitacion = {
  id: string;
  title: string;
  status: "processing" | "indexed" | "partial_error" | "error";
  estado: LicitacionEstado;
  resultado: boolean | null;
  deadline: string | null;
  created_at: string;
  updated_at: string;
  documents: Pliego[];
};

// ── Requisitos ──────────────────────────────────────────────────────────────

export type Requirement = {
  id: string;
  categoria: "administrativo" | "tecnico" | "economico" | "plazo";
  descripcion: string;
  pagina: number | null;
  documento_origen: string;
  es_obligatorio: boolean;
};

export type RequirementsList = {
  licitacion_id: string;
  requirements: Requirement[];
  cached: boolean;
  generated_at: string | null;
};

// ── Chat RAG ────────────────────────────────────────────────────────────────

export type Citation = {
  content: string;
  page_number: number | null;
  pliego_id: string;
  licitacion_id: string;
  filename: string;
  document_type: string;
};

export type QueryResponse = {
  answer: string;
  citations: Citation[];
};

export type QueryHistoryItem = {
  id: string;
  question: string;
  answer: string;
  citations: Citation[];
  created_at: string;
  session_id: string | null;
};

// ── Match ───────────────────────────────────────────────────────────────────

export type MatchCriterion = {
  criterio: string;
  puntuacion: number;
  justificacion: string;
};

export type MatchResponse = {
  licitacion_id: string;
  puntuacion_total: number;
  nivel_encaje: "Alto" | "Medio" | "Bajo";
  resumen: string;
  desglose: MatchCriterion[];
  cached: boolean;
};

// ── Perfil de empresa ───────────────────────────────────────────────────────

export type CompanyProfile = {
  id: string;
  name: string;
  description: string | null;
  sectors: string[];
  certifications: string[];
  employee_count: number | null;
  annual_revenue: string | null;
  notable_clients: string[];
  solvency_tech: string | null;
  solvency_econ: string | null;
  updated_at: string;
};

export type CompanyProfileInput = Omit<CompanyProfile, "id" | "updated_at">;

// ── Memoria Técnica ─────────────────────────────────────────────────────────

export type MemoriaSectionDraft = {
  title: string;
  description: string | null;
  criterio_adjudicacion: string | null;
  max_puntos: number | null;
  page_budget: number | null;
  sort_order: number;
};

export type MemoriaEsquemaResponse = {
  reply: string;
  esquema: MemoriaSectionDraft[];
};

export type MemoriaPropuestaResponse = {
  doc_id: string;
  title: string;
  markdown: string;
};

export type MemoriaDocument = {
  id: string;
  licitacion_id: string;
  title: string;
  markdown: string | null;
  updated_at: string | null;
};

export type MemoriaChatResponse = {
  markdown: string;
  texto_chat: string;
};
