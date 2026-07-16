import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { getToken } from "../lib/authToken";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
