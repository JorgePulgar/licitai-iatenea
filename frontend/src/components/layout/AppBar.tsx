import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';

interface AppBarProps {
  crumbs: string[];
}

export default function AppBar({ crumbs }: AppBarProps) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  function handleLogout() {
    logout();
    navigate('/login');
  }

  return (
    <div className="appbar">
      <div className="brand cursor-pointer" onClick={() => navigate('/pliegos')}>
        <span className="mark">L</span>
        <span>LicitAI</span>
      </div>

      <div className="crumbs">
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-[6px]">
            {i > 0 && <span className="sep">/</span>}
            <span className={i === crumbs.length - 1 ? 'now' : ''}>{c}</span>
          </span>
        ))}
      </div>

      <div className="right">
        <div
          className="input placeholder w-60 h-6 cursor-text select-none"
          title="Búsqueda global — próximamente"
        >
          <span className="flex-1 text-11">Buscar pliego, requisito, cláusula…</span>
          <span className="kbd">⌘K</span>
        </div>
        <span className="t-sm t-mute">{user?.email ?? 'Sin sesión'}</span>
        <button
          className="btn sm ghost"
          onClick={handleLogout}
          title="Cerrar sesión"
        >
          Salir
        </button>
      </div>
    </div>
  );
}
