import type {
  LicitacionResponse,
  LicitacionCreateRequest,
  LicitacionUpdateRequest,
  SasTokenResponse,
  HealthResponse,
  SummaryResponse,
  QueryRequest,
  QueryResponse,
  QueryHistoryItem,
  QuerySession,
  MatchResponse,
  RequirementsListResponse,
  CompanyProfileUpdate,
  CompanyProfileResponse,
} from '../types/licitacion';
import type { LoginRequest, TokenResponse, UserResponse } from '../types/auth';

const BASE = '/api/v1';

const TOKEN_KEY = 'licitai_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

async function handleResponse<T>(res: Response, skipAuthRedirect = false): Promise<T> {
  if (!res.ok) {
    if (res.status === 401 && !skipAuthRedirect && getToken()) {
      clearToken();
      window.location.href = '/login';
    }
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Auth ──

export async function login(body: LoginRequest): Promise<TokenResponse> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse<TokenResponse>(res, true);
}

export async function fetchMe(): Promise<UserResponse> {
  const res = await fetch(`${BASE}/auth/me`, {
    headers: authHeaders(),
  });
  return handleResponse<UserResponse>(res);
}

// ── Licitaciones ──

export async function fetchLicitaciones(skip = 0, limit = 100): Promise<LicitacionResponse[]> {
  const res = await fetch(`${BASE}/licitaciones/?skip=${skip}&limit=${limit}`, {
    headers: authHeaders(),
  });
  return handleResponse<LicitacionResponse[]>(res);
}

export async function fetchUploadToken(): Promise<SasTokenResponse> {
  const res = await fetch(`${BASE}/licitaciones/upload-token`, {
    headers: authHeaders(),
  });
  return handleResponse<SasTokenResponse>(res);
}

export async function fetchLicitacion(id: string): Promise<LicitacionResponse> {
  const res = await fetch(`${BASE}/licitaciones/${id}`, {
    headers: authHeaders(),
  });
  return handleResponse<LicitacionResponse>(res);
}

export async function createLicitacion(body: LicitacionCreateRequest): Promise<LicitacionResponse> {
  const res = await fetch(`${BASE}/licitaciones/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  return handleResponse<LicitacionResponse>(res);
}

export async function updateLicitacion(
  id: string,
  body: LicitacionUpdateRequest,
): Promise<LicitacionResponse> {
  const res = await fetch(`${BASE}/licitaciones/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  return handleResponse<LicitacionResponse>(res);
}

export async function deleteLicitacion(id: string): Promise<void> {
  const res = await fetch(`${BASE}/licitaciones/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
}

// ── Summary ──

export async function fetchSummary(licitacionId: string): Promise<SummaryResponse> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/summary`, {
    headers: authHeaders(),
  });
  return handleResponse<SummaryResponse>(res);
}

// ── Query / RAG ──

export async function queryLicitacion(body: QueryRequest): Promise<QueryResponse> {
  const res = await fetch(`${BASE}/query/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  return handleResponse<QueryResponse>(res);
}

export async function fetchQueryHistory(
  licitacionId: string,
  sessionId?: string,
): Promise<QueryHistoryItem[]> {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  const res = await fetch(`${BASE}/query/${licitacionId}/history${qs}`, {
    headers: authHeaders(),
  });
  return handleResponse<QueryHistoryItem[]>(res);
}

export async function fetchQuerySessions(licitacionId: string): Promise<QuerySession[]> {
  const res = await fetch(`${BASE}/query/${licitacionId}/sessions`, {
    headers: authHeaders(),
  });
  return handleResponse<QuerySession[]>(res);
}

// ── Document Viewer ──

export async function fetchDocumentViewUrl(licitacionId: string, pliegoId: string): Promise<string> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/documents/${pliegoId}/view-url`, {
    headers: authHeaders(),
  });
  const data = await handleResponse<{ url: string }>(res);
  return data.url;
}

// ── Requirements ──

export async function fetchRequirements(licitacionId: string): Promise<RequirementsListResponse> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/requirements`, {
    headers: authHeaders(),
  });
  return handleResponse<RequirementsListResponse>(res);
}

// ── Match Score ──

export async function fetchCachedMatch(licitacionId: string): Promise<MatchResponse | null> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/match`, {
    headers: authHeaders(),
  });
  if (res.status === 404) return null;
  return handleResponse<MatchResponse>(res);
}

export async function matchScore(licitacionId: string): Promise<MatchResponse> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/match`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
  });
  return handleResponse<MatchResponse>(res);
}

// ── Company Profile ──

export async function fetchCompanyProfile(): Promise<CompanyProfileResponse> {
  const res = await fetch(`${BASE}/perfil/`, {
    headers: authHeaders(),
  });
  return handleResponse<CompanyProfileResponse>(res);
}

export async function updateCompanyProfile(body: CompanyProfileUpdate): Promise<CompanyProfileResponse> {
  const res = await fetch(`${BASE}/perfil/`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  return handleResponse<CompanyProfileResponse>(res);
}

// ── Health ──

export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch('/health');
  return handleResponse<HealthResponse>(res);
}

// ── Memoria Técnica ──

import type {
  MemoriaEsquemaResponse,
  MemoriaSectionDraft,
  MemoriaSectionResponse,
  MemoriaPropuestaResponse,
  MemoriaDocChatResponse,
  MemoriaChatMessageResponse,
  MemoriaDocumentResponse
} from '../types/licitacion';

export async function fetchMemoriaDocuments(licitacionId: string): Promise<MemoriaDocumentResponse[]> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/documents`, {
    headers: authHeaders(),
  });
  return handleResponse<MemoriaDocumentResponse[]>(res);
}

export async function fetchMemoriaDocument(licitacionId: string, docId: string): Promise<MemoriaDocumentResponse> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/documents/${docId}`, {
    headers: authHeaders(),
  });
  return handleResponse<MemoriaDocumentResponse>(res);
}

export async function updateMemoriaDocument(
  licitacionId: string,
  docId: string,
  patch: { markdown?: string; title?: string }
): Promise<MemoriaDocumentResponse> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/documents/${docId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  });
  return handleResponse<MemoriaDocumentResponse>(res);
}

export async function generateMemoriaEsquema(
  licitacionId: string,
  message: string,
  templateIds: string[] = []
): Promise<MemoriaEsquemaResponse> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/esquema`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ message, template_ids: templateIds }),
  });
  return handleResponse<MemoriaEsquemaResponse>(res);
}

export async function saveMemoriaSections(licitacionId: string, sections: MemoriaSectionDraft[]): Promise<MemoriaSectionResponse[]> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/sections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ sections }),
  });
  return handleResponse<MemoriaSectionResponse[]>(res);
}

export async function generateMemoriaPropuesta(
  licitacionId: string,
  esquema: MemoriaSectionDraft[],
  templateIds: string[] = []
): Promise<MemoriaPropuestaResponse> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/propuesta`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ esquema, template_ids: templateIds }),
  });
  return handleResponse<MemoriaPropuestaResponse>(res);
}

export async function chatMemoria(licitacionId: string, docId: string, markdown: string, message: string): Promise<MemoriaDocChatResponse> {
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ doc_id: docId, markdown, message }),
  });
  return handleResponse<MemoriaDocChatResponse>(res);
}

export async function fetchMemoriaChatHistory(
  licitacionId: string,
  docId?: string
): Promise<MemoriaChatMessageResponse[]> {
  const qs = docId ? `?doc_id=${encodeURIComponent(docId)}` : '';
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/chat${qs}`, {
    headers: authHeaders(),
  });
  return handleResponse<MemoriaChatMessageResponse[]>(res);
}

// ── Plantillas de referencia (CompanyTemplate) ──

import type { CompanyTemplateResponse } from '../types/licitacion';

export async function fetchCompanyTemplates(): Promise<CompanyTemplateResponse[]> {
  const res = await fetch(`${BASE}/templates/`, {
    headers: authHeaders(),
  });
  return handleResponse<CompanyTemplateResponse[]>(res);
}

export async function uploadCompanyTemplate(
  file: File,
  opts: { title?: string; description?: string } = {}
): Promise<CompanyTemplateResponse> {
  const fd = new FormData();
  fd.append('file', file);
  if (opts.title) fd.append('title', opts.title);
  if (opts.description) fd.append('description', opts.description);
  const res = await fetch(`${BASE}/templates/`, {
    method: 'POST',
    headers: authHeaders(),
    body: fd,
  });
  return handleResponse<CompanyTemplateResponse>(res);
}

export async function updateCompanyTemplate(
  templateId: string,
  patch: { title?: string; description?: string }
): Promise<CompanyTemplateResponse> {
  const res = await fetch(`${BASE}/templates/${templateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  });
  return handleResponse<CompanyTemplateResponse>(res);
}

export async function deleteCompanyTemplate(templateId: string): Promise<void> {
  const res = await fetch(`${BASE}/templates/${templateId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
}

export async function exportMemoriaPdf(licitacionId: string, docId: string): Promise<Blob> {
  const token = getToken();
  const res = await fetch(`${BASE}/licitaciones/${licitacionId}/memoria/export`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify({ doc_id: docId }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.blob();
}


// ── Audit ─────────────────────────────────────────────────────────────────

export interface AuditLicitacionStats {
  total: number;
  by_status: Record<string, number>;
  created_last_7d: number;
  created_last_30d: number;
}

export interface AuditDocumentStats {
  total_pliegos: number;
  total_pages: number;
  total_size_mb: number;
  by_type: Record<string, number>;
}

export interface AuditMemoriaStats {
  total_documents: number;
  total_chat_messages: number;
  total_templates: number;
}

export interface AuditAIUsageStats {
  total_queries: number;
  total_tokens_prompt: number;
  total_tokens_completion: number;
  total_tokens: number;
  avg_latency_ms: number | null;
  queries_last_7d: number;
  queries_last_30d: number;
}

export interface AuditUserStats {
  total_users: number;
  active_users: number;
}

export interface AuditUserActivity {
  user_id: string;
  email: string;
  full_name: string | null;
  licitaciones_count: number;
  queries_count: number;
  tokens_total: number;
}

export interface AuditResponse {
  generated_at: string;
  licitaciones: AuditLicitacionStats;
  documents: AuditDocumentStats;
  memorias: AuditMemoriaStats;
  ai_usage: AuditAIUsageStats;
  users: AuditUserStats;
  user_activity: AuditUserActivity[];
}

export async function fetchSystemAudit(): Promise<AuditResponse> {
  const res = await fetch(`${BASE}/system/audit`, {
    headers: authHeaders(),
  });
  return handleResponse<AuditResponse>(res);
}
