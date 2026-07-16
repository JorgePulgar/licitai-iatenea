/**
 * Único módulo que toca el almacenamiento del token (spec-fe-design A3).
 * Punto de intercambio único para la migración a cookie httpOnly (Phase FE):
 * cambiar la implementación aquí no toca ningún otro fichero.
 */
const STORAGE_KEY = "pliexa.token";

export function getToken(): string | null {
  return sessionStorage.getItem(STORAGE_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(STORAGE_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
