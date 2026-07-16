import { http } from "../lib/http";
import type { TokenResponse } from "../types/api";

export function login(email: string, password: string): Promise<TokenResponse> {
  return http.post<TokenResponse>("/auth/login", { email, password });
}
