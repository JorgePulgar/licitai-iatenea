import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { checkHealth } from '../services/api';
import { useAuth } from '../hooks/useAuth';

interface ServiceStatus {
  name: string;
  status: 'ok' | 'err' | 'unknown';
  label: string;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, isAuthenticated } = useAuth();
  const [usuario, setUsuario] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [loggingIn, setLoggingIn] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [services, setServices] = useState<ServiceStatus[]>([
    { name: 'API backend',                status: 'unknown', label: 'comprobando…' },
    { name: 'Indexación',                 status: 'unknown', label: 'sin datos' },
    { name: 'OCR (Document Intelligence)',status: 'unknown', label: 'sin datos' },
    { name: 'LLM (Azure OpenAI)',         status: 'unknown', label: 'sin datos' },
    { name: 'Azure AI Search',            status: 'unknown', label: 'sin datos' },
  ]);

  // Si ya está autenticado, redirige a pliegos
  useEffect(() => {
    if (isAuthenticated) navigate('/pliegos', { replace: true });
  }, [isAuthenticated, navigate]);

  // No limpiar el token aquí — lo gestiona useAuth.
  // Si el token es inválido, fetchMe() falla y useAuth lo limpia automáticamente.

  useEffect(() => {
    checkHealth()
      .then((h) =>
        setServices((prev) =>
          prev.map((s) =>
            s.name === 'API backend'
              ? { ...s, status: h.status === 'ok' ? 'ok' : 'err', label: h.status === 'ok' ? 'operativo' : 'error' }
              : s,
          ),
        ),
      )
      .catch(() =>
        setServices((prev) =>
          prev.map((s) =>
            s.name === 'API backend' ? { ...s, status: 'err', label: 'sin conexión' } : s,
          ),
        ),
      );
  }, []);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    if (!usuario.trim() || !password) return;

    setLoggingIn(true);
    setLoginError(null);

    try {
      await login(usuario.trim(), password.trim());
      navigate('/pliegos');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Error desconocido';
      if (msg.includes('401')) {
        setLoginError('Credenciales incorrectas');
      } else {
        setLoginError('Error de conexión. Comprueba que el backend está activo.');
      }
    } finally {
      setLoggingIn(false);
    }
  }

  const dotCls = (s: ServiceStatus['status']) =>
    s === 'ok' ? 'dot ok' : s === 'err' ? 'dot err' : 'dot idle';

  return (
    <div className="flex h-screen bg-surface font-sans">
      {/* Left panel — service status */}
      <div className="w-[380px] p-10 bg-surface-2 border-r border-line flex flex-col justify-between shrink-0">
        <div className="flex items-center gap-2">
          <span className="mark">L</span>
          <span className="font-semibold text-13">LicitAI</span>
        </div>

        <div className="flex flex-col gap-3">
          <div className="t-up">Estado del servicio</div>
          <div className="flex flex-col gap-2">
            {services.map((s) => (
              <div key={s.name} className="flex justify-between items-center text-12">
                <span className="text-ink-2">{s.name}</span>
                <span className="flex items-center gap-2">
                  <span className={dotCls(s.status)} />
                  <span className="t-mute">{s.label}</span>
                </span>
              </div>
            ))}
          </div>

          <div className="h-px bg-line mt-2" />

          <div className="flex flex-col gap-1 text-11 text-ink-3">
            {[
              ['Entorno',  'licitai-dev'],
              ['Versión',  'v0.4.2 · 2026-05-12'],
              ['Región',   'westeurope'],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="mono">{v}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="help">
          Soporte: soporte@licitai.app
          <br />
          Incidencias: ServiceNow · cola LIC-OPS
        </div>
      </div>

      {/* Right panel — login form */}
      <div className="flex flex-1 items-center justify-center">
        <form onSubmit={handleLogin} className="w-[320px]">
          <div className="t-2xl">Iniciar sesión</div>
          <p className="help mt-1">Usa tu cuenta de Microsoft Entra ID corporativa.</p>

          <div className="flex flex-col gap-3 mt-3">
            <button
              type="button"
              className="btn lg w-full justify-center"
              disabled={loggingIn}
              title="Autenticación Microsoft Entra ID — pendiente de implementación"
            >
              <span className="w-[14px] h-[14px] border border-line-strong rounded-sm shrink-0" />
              Continuar con Microsoft 365
            </button>

            <div className="flex items-center gap-2">
              <div className="h-px bg-line flex-1" />
              <span className="t-xs t-mute">acceso alternativo</span>
              <div className="h-px bg-line flex-1" />
            </div>

            <div>
              <label className="label">Usuario corporativo</label>
              <input
                className="real-input"
                type="email"
                placeholder="usuario@empresa.es"
                value={usuario}
                onChange={(e) => setUsuario(e.target.value)}
                autoComplete="email"
              />
            </div>

            <div>
              <label className="label">Contraseña</label>
              <div className="input h-[28px]">
                <input
                  type={showPassword ? 'text' : 'password'}
                  placeholder="••••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="bg-transparent border-0 cursor-pointer text-10 text-ink-3 p-0 shrink-0"
                >
                  {showPassword ? 'ocultar' : 'mostrar'}
                </button>
              </div>
            </div>

            {loginError && (
              <div className="text-12 text-red-500 bg-red-50 border border-red-200 rounded px-3 py-2">
                {loginError}
              </div>
            )}

            <div className="flex justify-between items-center text-11 text-ink-3">
              <label className="flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                Recordar sesión
              </label>
              <span
                className="text-accent cursor-pointer text-11"
                title="Recuperación de acceso — pendiente de implementación"
              >
                Recuperar acceso
              </span>
            </div>

            <button
              type="submit"
              className="btn lg primary w-full justify-center mt-1"
              disabled={loggingIn || !usuario.trim() || !password}
            >
              {loggingIn ? 'Accediendo…' : 'Entrar'}
              {!loggingIn && (
                <span className="kbd border-white/30 bg-transparent text-white/70">↵</span>
              )}
            </button>
          </div>

          <div className="help mt-4 text-center pt-4 border-t border-line">
            Acceso restringido al personal autorizado.
          </div>
        </form>
      </div>
    </div>
  );
}
