import { http } from "../lib/http";
import type { QueryHistoryItem, QueryResponse } from "../types/api";

export function askQuestion(input: {
  question: string;
  licitacion_id: string;
  session_id?: string;
}): Promise<QueryResponse> {
  return http.post<QueryResponse>("/query/", input);
}

export function getHistory(
  licitacionId: string,
  sessionId?: string,
): Promise<QueryHistoryItem[]> {
  const params = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return http.get<QueryHistoryItem[]>(`/query/${licitacionId}/history${params}`);
}
