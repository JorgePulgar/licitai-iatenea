import type { FormEvent } from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { ApiError } from "../lib/http";
import { setToken } from "../lib/authToken";
import { login } from "../services/auth";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await login(email, password);
      setToken(access_token);
      navigate("/licitaciones");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Credenciales incorrectas"
          : "No se pudo iniciar sesión. Inténtalo de nuevo.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      <div className="hidden flex-1 items-center bg-accent md:flex">
        <div className="px-12 text-white">
          <h1 className="text-3xl font-semibold">Pliexa</h1>
          <p className="mt-3 max-w-md text-white/80">
            Análisis de licitaciones públicas con IA: requisitos, consultas con citas y
            borradores de memoria técnica.
          </p>
        </div>
      </div>
      <div className="flex flex-1 items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-4">
          <h2 className="text-xl font-semibold text-ink-1 md:hidden">Pliexa</h2>
          <h3 className="text-lg font-medium text-ink-1">Iniciar sesión</h3>
          <Input
            label="Email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            label="Contraseña"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="text-sm text-danger">{error}</p>}
          <Button type="submit" loading={busy} className="w-full">
            Entrar
          </Button>
        </form>
      </div>
    </div>
  );
}
