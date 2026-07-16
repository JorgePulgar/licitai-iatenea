import { http } from "../lib/http";
import type { CompanyProfile, CompanyProfileInput } from "../types/api";

export function getProfile(): Promise<CompanyProfile> {
  return http.get<CompanyProfile>("/perfil/");
}

export function saveProfile(input: CompanyProfileInput): Promise<CompanyProfile> {
  return http.put<CompanyProfile>("/perfil/", input);
}
