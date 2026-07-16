import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../lib/authToken";

const NAV_ITEMS = [
  { to: "/licitaciones", label: "Licitaciones" },
  { to: "/perfil", label: "Perfil de empresa" },
];

/** Shell: sidebar colapsable + topbar (spec-fe-design A3); drawer bajo md. */
export function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const navigate = useNavigate();

  const logout = () => {
    clearToken();
    navigate("/login");
  };

  const nav = (
    <nav className="flex flex-col gap-1 p-3">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          onClick={() => setDrawerOpen(false)}
          className={({ isActive }) =>
            `rounded px-3 py-2 text-sm font-medium transition-colors duration-150 ${
              isActive ? "bg-accent/10 text-accent" : "text-ink-2 hover:bg-line/50"
            }`
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 border-r border-line bg-surface md:block">
        <div className="border-b border-line px-4 py-4 text-lg font-semibold text-ink-1">
          Pliexa
        </div>
        {nav}
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-20 md:hidden">
          <div
            className="absolute inset-0 bg-ink-1/30"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <aside className="absolute inset-y-0 left-0 w-56 border-r border-line bg-surface">
            <div className="border-b border-line px-4 py-4 text-lg font-semibold">Pliexa</div>
            {nav}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-line bg-surface px-4">
          <button
            type="button"
            className="rounded px-2 py-1 text-ink-2 hover:bg-line/50 md:hidden"
            onClick={() => setDrawerOpen(true)}
            aria-label="Abrir menú"
          >
            ☰
          </button>
          <span className="text-sm text-ink-3 max-md:hidden">
            Análisis de licitaciones públicas
          </span>
          <button
            type="button"
            onClick={logout}
            className="rounded px-3 py-1 text-sm text-ink-2 hover:bg-line/50"
          >
            Cerrar sesión
          </button>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
