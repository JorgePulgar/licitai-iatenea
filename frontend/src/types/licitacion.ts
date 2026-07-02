// ── Document types ──

export type DocumentType = 'pcap' | 'ppt' | 'anexo';

// ── Statuses ──

export type PliegoStatus = 'uploaded' | 'processing' | 'indexed' | 'error';
export type LicitacionStatus = 'processing' | 'indexed' | 'partial_error' | 'error';

// Estado comercial editable (distinto del estado de pipeline `status`).
export type LicitacionEstado = 'elaborando' | 'revision_comercial' | 'entregada' | 'resuelta';

// ── Pliego (individual document within a Licitacion) ──

export interface PliegoResponse {
  id: string;
  licitacion_id: string;
  document_type: DocumentType;
  filename: string;
  doc_title: string | null;
  blob_url: string;
  size_bytes: number;
  uploaded_at: string;
  processed_at: string | null;
  status: PliegoStatus;
  user_id: string;
}

// ── Licitacion (parent entity grouping PCAP + PPT + N anexos) ──

export interface DocumentUploadInfo {
  blob_url: string;
  filename: string;
  size_bytes: number;
}

export interface SasTokenResponse {
  sas_token: string;
  container: string;
  account: string;
}

export interface LicitacionCreateRequest {
  title: string;
  pcap: DocumentUploadInfo;
  ppt?: DocumentUploadInfo;
  anexos: DocumentUploadInfo[];
  deadline?: string | null; // ISO date (YYYY-MM-DD)
}

export interface LicitacionUpdateRequest {
  estado?: LicitacionEstado;
  resultado?: boolean | null;
  deadline?: string | null; // ISO date (YYYY-MM-DD), null para borrar
}

export interface LicitacionResponse {
  id: string;
  user_id: string;
  title: string;
  status: LicitacionStatus;
  estado: LicitacionEstado;
  resultado: boolean | null;
  deadline: string | null; // ISO date (YYYY-MM-DD)
  created_at: string;
  updated_at: string;
  documents: PliegoResponse[];
}

// ── Tab keys ──

export type TabKey = 'resumen' | 'chat' | 'requisitos' | 'match' | 'memoria' | 'documento' | 'auditoria';

// ── Summary ──

export interface SummaryResponse {
  licitacion_id: string;
  objeto: string;
  presupuesto: string | null;
  plazo_ejecucion: string | null;
  solvencia_tecnica: string[];
  solvencia_economica: string[];
  criterios_adjudicacion: string[];
  plazos_clave: string[];
  resumen: string;
}

// ── Query / RAG ──

export interface Citation {
  content: string;
  page_number: number | null;
  pliego_id: string;
  licitacion_id: string;
  filename: string;
  document_type: DocumentType;
}

export interface QueryRequest {
  question: string;
  licitacion_id: string;
  document_type?: DocumentType;
  session_id?: string;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
}

export interface QueryHistoryItem {
  id: string;
  question: string;
  answer: string;
  citations: Citation[];
  created_at: string;
  session_id?: string | null;
}

export interface QuerySession {
  session_id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

// ── Company Profile ──

export interface CompanyProfileUpdate {
  name: string;
  description?: string;
  sectors?: string[];
  certifications?: string[];
  employee_count?: number;
  annual_revenue?: string;
  notable_clients?: string[];
  solvency_tech?: string;
  solvency_econ?: string;
}

export interface CompanyProfileResponse {
  id: string;
  name: string;
  description?: string;
  sectors: string[];
  certifications: string[];
  employee_count?: number;
  annual_revenue?: string;
  notable_clients: string[];
  solvency_tech?: string;
  solvency_econ?: string;
  is_default: boolean;
  updated_at: string;
}

// ── Requirements ──

export interface RequirementResponse {
  id: string;
  categoria: 'administrativo' | 'solvencia_tecnica' | 'solvencia_economica' | 'tecnico' | 'criterio_adjudicacion';
  descripcion: string;
  pagina: number | null;
  documento_origen: string;
  es_obligatorio: boolean;
}

export interface RequirementsListResponse {
  licitacion_id: string;
  requirements: RequirementResponse[];
  cached: boolean;
  generated_at: string | null;
}

// ── Match Score ──

export interface MatchCriterion {
  criterio: string;
  puntuacion: number;
  justificacion: string;
}

export interface RequirementMatch {
  requisito_id: string;
  descripcion: string;
  categoria: string;
  estado: 'cumplido' | 'no_cumplido' | 'indeterminado';
  justificacion: string;
  pagina: number | null;
  documento_origen: string | null;
}

export interface MatchResponse {
  licitacion_id: string;
  puntuacion_total: number;
  nivel_encaje: string;
  resumen: string;
  desglose: MatchCriterion[];
  requisitos_evaluados: RequirementMatch[];
  cached: boolean;
}

// ── Health ──

export interface HealthResponse {
  status: string;
  version: string;
}

// ── Memoria Técnica ──

export interface MemoriaSectionDraft {
  title: string;
  description?: string;
  criterio_adjudicacion?: string;
  max_puntos?: number | null;
  page_budget?: number | null;
  sort_order: number;
}

export interface MemoriaSectionResponse extends MemoriaSectionDraft {
  id: string;
  status: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface MemoriaEsquemaResponse {
  reply: string;
  esquema: MemoriaSectionDraft[];
}

export interface MemoriaPropuestaResponse {
  doc_id: string;
  title: string;
  markdown: string;
}

export interface MemoriaChatMessageResponse {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface MemoriaDocChatResponse {
  markdown: string;
  texto_chat: string;
}

export interface MemoriaDocumentResponse {
  id: string;
  licitacion_id: string;
  title: string;
  markdown: string | null;
  updated_at: string | null;
}

// ── Plantillas de referencia (CompanyTemplate) ──

export interface CompanyTemplateResponse {
  id: string;
  filename: string;
  title?: string | null;
  description?: string | null;
  mime_type: string;
  file_size?: number | null;
  page_count?: number | null;
  has_summary: boolean;
  created_at: string;
}
