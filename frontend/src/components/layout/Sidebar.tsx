import { NavLink } from 'react-router-dom';

interface SidebarProps {
  licitacionCount?: number;
  queueCount?: number;
}

export default function Sidebar({ licitacionCount, queueCount }: SidebarProps) {
  const navItemClass = ({ isActive }: { isActive: boolean }) =>
    `item${isActive ? ' active' : ''}`;

  return (
    <div className="sidenav">
      <div className="section-label">Trabajo</div>

      <NavLink to="/licitaciones" className={navItemClass}>
        <span className="ic" />
        <span>Licitaciones</span>
        {licitacionCount !== undefined && (
          <span className="count">{licitacionCount}</span>
        )}
      </NavLink>

      <NavLink to="/cola-procesado" className={navItemClass}>
        <span className="ic" />
        <span>Cola de procesado</span>
        {queueCount !== undefined && queueCount > 0 && (
          <span className="count">{queueCount}</span>
        )}
      </NavLink>

      <div className="flex-1" />

      <div className="section-label">Sistema</div>

      <NavLink to="/auditoria" className={navItemClass}>
        <span className="ic" />
        <span>Auditoría</span>
      </NavLink>

      <NavLink to="/settings" className={navItemClass}>
        <span className="ic" />
        <span>Ajustes</span>
      </NavLink>
    </div>
  );
}
