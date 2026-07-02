import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import AppShell from '../components/layout/AppShell';
import CommercialStateBadge from '../components/ui/CommercialStateBadge';
import { useLicitaciones } from '../hooks/useLicitaciones';
import { COMMERCIAL_OPTIONS, resolveCommercialOption } from '../utils/commercialState';

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('es-ES', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDeadline(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' });
}

function shortId(id: string): string {
  return id.slice(0, 8).toUpperCase();
}

// ── Filtros de fecha ──
type DateMode = 'none' | 'soonest' | 'latest' | 'week' | 'month' | 'overdue' | 'range';

const DATE_MODES: { key: DateMode; label: string }[] = [
  { key: 'none',    label: 'Sin orden por fecha' },
  { key: 'soonest', label: 'Fecha límite: más próxima' },
  { key: 'latest',  label: 'Fecha límite: más lejana' },
  { key: 'week',    label: 'Vence esta semana' },
  { key: 'month',   label: 'Vence este mes' },
  { key: 'overdue', label: 'Vencidas' },
  { key: 'range',   label: 'Rango de fechas…' },
];

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function LicitacionesPage() {
  const navigate = useNavigate();
  const { licitaciones, loading, error, reload } = useLicitaciones(10_000);
  const [search, setSearch] = useState('');
  const [estadoFilter, setEstadoFilter] = useState('');       // '' = todos
  const [dateMode, setDateMode] = useState<DateMode>('none');
  const [rangeFrom, setRangeFrom] = useState('');
  const [rangeTo, setRangeTo] = useState('');

  const availableLicitaciones = useMemo(() => {
    let list = licitaciones.filter((l) => l.status === 'indexed');

    // Búsqueda por texto
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (l) =>
          l.title.toLowerCase().includes(q) ||
          l.id.toLowerCase().includes(q) ||
          l.documents.some((d) => d.filename.toLowerCase().includes(q)),
      );
    }

    // Filtro por estado comercial
    if (estadoFilter) {
      list = list.filter(
        (l) => resolveCommercialOption(l.estado, l.resultado).key === estadoFilter,
      );
    }

    // Filtro por fecha límite (presets / rango)
    const today = todayISO();
    if (dateMode === 'week' || dateMode === 'month' || dateMode === 'overdue' || dateMode === 'range') {
      list = list.filter((l) => {
        if (!l.deadline) return false;
        if (dateMode === 'overdue') return l.deadline < today;
        if (dateMode === 'week') {
          const now = new Date();
          // Lunes como inicio de semana (getDay: 0=domingo)
          const daysSinceMonday = (now.getDay() + 6) % 7;
          const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysSinceMonday)
            .toISOString().slice(0, 10);
          const weekEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysSinceMonday + 6)
            .toISOString().slice(0, 10);
          return l.deadline >= weekStart && l.deadline <= weekEnd;
        }
        if (dateMode === 'month') {
          const now = new Date();
          const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
          const monthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().slice(0, 10);
          return l.deadline >= monthStart && l.deadline <= monthEnd;
        }
        // range
        if (rangeFrom && l.deadline < rangeFrom) return false;
        if (rangeTo && l.deadline > rangeTo) return false;
        return true;
      });
    }

    // Ordenación
    if (dateMode === 'soonest' || dateMode === 'latest') {
      list = [...list].sort((a, b) => {
        // sin fecha siempre al final
        if (!a.deadline && !b.deadline) return 0;
        if (!a.deadline) return 1;
        if (!b.deadline) return -1;
        return dateMode === 'soonest'
          ? a.deadline.localeCompare(b.deadline)
          : b.deadline.localeCompare(a.deadline);
      });
    } else {
      list = [...list].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
    }

    return list;
  }, [licitaciones, search, estadoFilter, dateMode, rangeFrom, rangeTo]);

  const processingCount = licitaciones.filter((l) => l.status === 'processing').length;
  const indexedCount = licitaciones.filter((l) => l.status === 'indexed').length;

  return (
    <AppShell
      crumbs={['Licitaciones']}
      licitacionCount={licitaciones.length}
      queueCount={processingCount}
      statusItems={[`${indexedCount} disponibles`]}
    >
      {/* Toolbar */}
      <div className="toolbar flex-wrap gap-2">
        <div className="input w-[260px]">
          <input
            placeholder="Buscar licitación..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <span className="kbd">/</span>
        </div>

        <select
          className="real-input py-1 text-12"
          style={{ width: 'auto' }}
          value={estadoFilter}
          onChange={(e) => setEstadoFilter(e.target.value)}
        >
          <option value="">Todos los estados</option>
          {COMMERCIAL_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </select>

        <select
          className="real-input py-1 text-12"
          style={{ width: 'auto' }}
          value={dateMode}
          onChange={(e) => setDateMode(e.target.value as DateMode)}
        >
          {DATE_MODES.map((m) => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>

        {dateMode === 'range' && (
          <>
            <input
              type="date"
              className="real-input py-1 text-12"
              style={{ width: 'auto' }}
              value={rangeFrom}
              onChange={(e) => setRangeFrom(e.target.value)}
              title="Desde"
            />
            <input
              type="date"
              className="real-input py-1 text-12"
              style={{ width: 'auto' }}
              value={rangeTo}
              onChange={(e) => setRangeTo(e.target.value)}
              title="Hasta"
            />
          </>
        )}

        <div className="flex-1" />

        <span className="t-xs t-mute">
          {availableLicitaciones.length} de {indexedCount}
        </span>

        <button
          className="btn sm primary"
          onClick={() => navigate('/licitaciones/nueva')}
        >
          + Nueva licitación{' '}
          <span className="kbd">N</span>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto bg-bg">
        {loading && (
          <div className="flex items-center justify-center p-12">
            <span className="t-mute">Cargando licitaciones…</span>
          </div>
        )}

        {error && !loading && (
          <div className="flex flex-col items-center justify-center gap-2 p-12">
            <div className="tag err">Error de conexión</div>
            <div className="help text-center">
              No se puede conectar con el backend: {error}
            </div>
            <button className="btn sm" onClick={reload}>Reintentar</button>
          </div>
        )}

        {!loading && !error && availableLicitaciones.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 p-12">
            <div className="t-mute">
              {search || estadoFilter || dateMode !== 'none'
                ? 'Sin resultados para los filtros aplicados'
                : 'No hay licitaciones disponibles. Crea la primera.'}
            </div>
            {!search && !estadoFilter && dateMode === 'none' && (
              <button className="btn primary" onClick={() => navigate('/licitaciones/nueva')}>
                Nueva licitación
              </button>
            )}
          </div>
        )}

        {!loading && !error && availableLicitaciones.length > 0 && (
          <table className="table compact rounded-none">
            <thead>
              <tr>
                <th className="w-[90px]">ID</th>
                <th>Título</th>
                <th className="w-[180px]">Estado</th>
                <th className="w-[130px]">Fecha límite</th>
                <th className="w-[240px]">Documentos</th>
                <th className="w-[140px]">Creada</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {availableLicitaciones.map((l) => {
                const overdue = !!l.deadline && l.deadline < todayISO() && l.estado !== 'resuelta';
                return (
                  <tr
                    key={l.id}
                    className="cursor-pointer hover:bg-surface-hover transition-colors"
                    onClick={() => navigate(`/licitaciones/${l.id}`)}
                  >
                    <td className="num t-mute text-11">
                      {shortId(l.id)}
                    </td>
                    <td>
                      <span className="t-medium text-12 truncate max-w-[360px] block" title={l.title}>
                        {l.title}
                      </span>
                      <div className="t-xs t-mute mono mt-0.5">{l.id}</div>
                    </td>
                    <td>
                      <CommercialStateBadge estado={l.estado} resultado={l.resultado} />
                    </td>
                    <td className={`num text-11 ${overdue ? 'text-err' : 't-mute'}`} title={overdue ? 'Plazo vencido' : undefined}>
                      {formatDeadline(l.deadline)}
                    </td>
                    <td>
                      <div className="flex items-center gap-1.5 overflow-hidden">
                        {l.documents.slice(0, 3).map(d => (
                          <span key={d.id} className="tag flex items-center gap-1 px-1.5 py-0.5 bg-bg border border-line" title={d.filename}>
                            <span className="opacity-60 text-[10px] uppercase tracking-wider">{d.document_type}</span>
                            <span className="truncate text-11 max-w-[100px]">{d.filename}</span>
                          </span>
                        ))}
                        {l.documents.length > 3 && (
                          <span className="text-[10px] t-mute shrink-0">
                            +{l.documents.length - 3}
                          </span>
                        )}
                        {l.documents.length === 0 && (
                          <span className="text-11 t-mute">Sin documentos</span>
                        )}
                      </div>
                    </td>
                    <td className="num t-mute text-11">
                      {formatDate(l.created_at)}
                    </td>
                    <td className="text-right text-mute opacity-0 group-hover:opacity-100 transition-opacity">
                      <span className="t-lg leading-none">›</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </AppShell>
  );
}
