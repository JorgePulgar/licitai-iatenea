/**
 * 1 smoke test por pantalla FE-minimal (spec-demo-minimal §3): login,
 * lista de licitaciones, detalle (requisitos), memoria y perfil.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { setToken } from "../lib/authToken";
import { LicitacionDetailPage } from "../pages/LicitacionDetailPage";
import { LicitacionesPage } from "../pages/LicitacionesPage";
import { LoginPage } from "../pages/LoginPage";
import { PerfilPage } from "../pages/PerfilPage";

function renderAt(path: string, ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/licitaciones" element={<LicitacionesPage />} />
          <Route path="/licitaciones/:id/:tab?" element={<LicitacionDetailPage />} />
          <Route path="/perfil" element={<PerfilPage />} />
          <Route path="*" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("pantallas FE-minimal", () => {
  it("login: hace login y guarda el token", async () => {
    const user = userEvent.setup();
    renderAt("/login", <LoginPage />);

    await user.type(screen.getByLabelText("Email"), "jorge@pliexa.es");
    await user.type(screen.getByLabelText("Contraseña"), "secreta123");
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    // Tras el login la ruta protegida /licitaciones carga la lista.
    expect(await screen.findByText("Servicio de mantenimiento de aplicaciones"))
      .toBeInTheDocument();
    expect(sessionStorage.getItem("pliexa.token")).toBe("token-123");
  });

  it("licitaciones: lista con estado de pipeline", async () => {
    setToken("token-123");
    renderAt("/licitaciones", <LicitacionesPage />);

    expect(await screen.findByText("Servicio de mantenimiento de aplicaciones"))
      .toBeInTheDocument();
    expect(screen.getByText("Indexada")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nueva licitación" })).toBeInTheDocument();
  });

  it("detalle: pestaña de requisitos con checklist y página de origen", async () => {
    setToken("token-123");
    renderAt("/licitaciones/lic-1/requisitos", <LicitacionDetailPage />);

    expect(
      await screen.findByText("Equipo mínimo de 3 desarrolladores senior"),
    ).toBeInTheDocument();
    expect(screen.getByText("obligatorio")).toBeInTheDocument();
    expect(screen.getByText(/\[ppt p\. 14\]/)).toBeInTheDocument();
  });

  it("memoria: borrador renderizado con marcador [COMPLETAR] visible", async () => {
    setToken("token-123");
    renderAt("/licitaciones/lic-1/memoria", <LicitacionDetailPage />);

    const marker = await screen.findByText(/\[COMPLETAR: certificaciones de calidad\]/);
    // Resaltado, no perdido en el texto (spec-memoria-prompts §7).
    expect(marker.tagName).toBe("MARK");
    expect(screen.getByRole("button", { name: "Aplicar cambio" })).toBeInTheDocument();
  });

  it("perfil: carga el perfil existente en el formulario", async () => {
    setToken("token-123");
    renderAt("/perfil", <PerfilPage />);

    expect(await screen.findByDisplayValue("Iatenea SL")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar perfil" })).toBeInTheDocument();
  });
});
