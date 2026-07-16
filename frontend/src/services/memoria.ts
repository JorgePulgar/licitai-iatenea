import { http } from "../lib/http";
import type {
  MemoriaChatResponse,
  MemoriaDocument,
  MemoriaEsquemaResponse,
  MemoriaPropuestaResponse,
  MemoriaSectionDraft,
} from "../types/api";

const base = (licitacionId: string) => `/licitaciones/${licitacionId}/memoria`;

export function proposeEsquema(
  licitacionId: string,
  message = "",
): Promise<MemoriaEsquemaResponse> {
  return http.post<MemoriaEsquemaResponse>(`${base(licitacionId)}/esquema`, { message });
}

export function generatePropuesta(
  licitacionId: string,
  esquema: MemoriaSectionDraft[],
): Promise<MemoriaPropuestaResponse> {
  return http.post<MemoriaPropuestaResponse>(`${base(licitacionId)}/propuesta`, { esquema });
}

export function listDocuments(licitacionId: string): Promise<MemoriaDocument[]> {
  return http.get<MemoriaDocument[]>(`${base(licitacionId)}/documents`);
}

export function refineViaChat(
  licitacionId: string,
  input: { doc_id: string; markdown: string; message: string },
): Promise<MemoriaChatResponse> {
  return http.post<MemoriaChatResponse>(`${base(licitacionId)}/chat`, input);
}
