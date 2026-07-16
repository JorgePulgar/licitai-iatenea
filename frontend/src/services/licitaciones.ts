import { http } from "../lib/http";
import type { Licitacion, MatchResponse, RequirementsList } from "../types/api";

export function listLicitaciones(): Promise<Licitacion[]> {
  return http.get<Licitacion[]>("/licitaciones/");
}

export function getLicitacion(id: string): Promise<Licitacion> {
  return http.get<Licitacion>(`/licitaciones/${id}`);
}

/**
 * Alta con subida server-side (spec-demo-minimal §3.3: el flujo SAS de spec-1.1
 * no ha aterrizado; el navegador NUNCA recibe un SAS de contenedor — finding #1).
 */
export function createLicitacion(input: {
  title: string;
  pcap: File;
  ppt?: File;
  deadline?: string;
}): Promise<Licitacion> {
  const form = new FormData();
  form.append("title", input.title);
  form.append("pcap", input.pcap);
  if (input.ppt) form.append("ppt", input.ppt);
  if (input.deadline) form.append("deadline", input.deadline);
  return http.postForm<Licitacion>("/licitaciones/upload", form);
}

export function getRequirements(licitacionId: string): Promise<RequirementsList> {
  return http.get<RequirementsList>(`/licitaciones/${licitacionId}/requirements`);
}

export function computeMatch(licitacionId: string): Promise<MatchResponse> {
  return http.post<MatchResponse>(`/licitaciones/${licitacionId}/match`);
}
