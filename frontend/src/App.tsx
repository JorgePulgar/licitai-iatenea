import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LicitacionDetailPage } from "./pages/LicitacionDetailPage";
import { LicitacionesPage } from "./pages/LicitacionesPage";
import { LoginPage } from "./pages/LoginPage";
import { PerfilPage } from "./pages/PerfilPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route path="/licitaciones" element={<LicitacionesPage />} />
            <Route path="/licitaciones/:id/:tab?" element={<LicitacionDetailPage />} />
            <Route path="/perfil" element={<PerfilPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/licitaciones" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
