import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import AppShell from '../components/layout/AppShell';
import StateTag from '../components/ui/StateTag';
import { useLicitaciones } from '../hooks/useLicitaciones';
import { deleteLicitacion } from '../services/api';
import { useModal } from '../hooks/useModal';
import type { LicitacionResponse, LicitacionStatus } from '../types/licitacion';

type FilterStatus = 'all' | LicitacionStatus;

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

function shortId(id: string): string {
  return id.slice(0, 8).toUpperCase();
}

function docCountLabel(lic: LicitacionResponse): string {
  const count = lic.documents.length;
  return `${count} doc${count !== 1 ? 's' : ''}`;
}

export default function ColaProcesadoPage() {
  const navigate = useNavigate();
  const { showModal } = useModal();
  const { licitaciones, loading, error, reload } = useLicitaciones(10_000);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<string | null>(null);
  const [statusDropdown, setStatusDropdown] = useState(false);
  const [rowsPerPage] = useState(50);
  const [page, setPage] = useState(1);

  const counts = useMemo(() => {
    const c = { all: licitaciones.length, processing: 0, indexed: 0, partial_error: 0, error: 0 };
    licitaciones.forEach((l) => {
      if (l.status in c) c[l.status as keyof Omit<typeof c, 'all'>]++;
    });
    return c;
  }, [licitaciones]);

  const queueCount = counts.processing;

  const filtered = useMemo(() => {
    let list = licitaciones;
    if (filterStatus !== 'all') list = list.filter((l) => l.status === filterStatus);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (l) =>
          l.title.toLowerCase().includes(q) ||
          l.id.toLowerCase().includes(q) ||
          l.documents.some((d) => d.filename.toLowerCase().includes(q)),
      );
    }
    return list;
  }, [licitaciones, filterStatus, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / rowsPerPage));
  const pageItems = filtered.slice((page - 1) * rowsPerPage, page * rowsPerPage);

  const allSelectedOnPage = pageItems.length > 0 && pageItems.every((l) => selected.has(l.id));

  function toggleSelectAll() {
    if (allSelectedOnPage) {
      const next = new Set(selected);
      pageItems.forEach((l) => next.delete(l.id));
      setSelected(next);
    } else {
      const next = new Set(selected);
      pageItems.forEach((l) => next.add(l.id));
      setSelected(next);
    }
  }

  function toggleSelect(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  async function handleDelete(lic: LicitacionResponse) {
    const confirmed = await showModal({
      type: 'confirmation',
      title: 'Eliminar licitación',
      description: <>Se eliminarán <strong>{lic.title}</strong> y todos sus documentos. Esta acción no se puede deshacer.</>,
      tone: 'danger',
      confirmLabel: 'Eliminar',
    });
    if (!confirmed) return;

    setDeleting(lic.id);
    try {
      await deleteLicitacion(lic.id);
      await reload();
      setSelected((s) => { const n = new Set(s); n.delete(lic.id); return n; });
    } catch (e) {
      await showModal({
        type: 'alert',
        title: 'No se pudo eliminar la licitación',
        description: e instanceof Error ? e.message : String(e),
        tone: 'danger',
      });
    } finally {
      setDeleting(null);
    }
  }

  function exportCsv() {
    const header = ['ID', 'Título', 'Estado', 'Documentos', 'Creada', 'Actualizada'];
    const rows = filtered.map((l) => [
      l.id,
      l.title,
      l.status,
      String(l.documents.length),
      l.created_at,
      l.updated_at,
    ]);
    const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `licitaciones_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const tabs: [FilterStatus, string, number | string][] = [
    ['all', 'Todas', counts.all],
    ['processing', 'En proceso', counts.processing],
    ['indexed', 'Listas', counts.indexed],
    ['partial_error', 'Parcial', counts.partial_error],
    ['error', 'Error', counts.error],
  ];

  return (
    <AppShell
      crumbs={['Cola de procesado']}
      licitacionCount={licitaciones.length}
      queueCount={queueCount}
      statusItems={[`${licitaciones.length} licitaciones · ${queueCount} en proceso`]}
    >
      {/* Tab navbar */}
      <div className="navbar">
        {tabs.map(([key, label, count]) => (
          <div
            key={key}
            className={`item${filterStatus === key ? ' active' : ''}`}
            onClick={() => { setFilterStatus(key); setPage(1); }}
          >
            {label}
            <span className="count">{count}</span>
          </div>
        ))}
        <div className="flex-1" />
      </div>

      {/* Toolbar */}
      <div className="toolbar">
        <div className="input w-[280px]">
          <input
            placeholder="Buscar por título, nombre o ID…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
          <span className="kbd">/</span>
        </div>

        {/* Status filter dropdown */}
        <div className="relative">
          <button
            className="btn sm"
            onClick={() => setStatusDropdown((v) => !v)}
            onBlur={() => setTimeout(() => setStatusDropdown(false), 150)}
          >
            Estado{filterStatus !== 'all' ? ` · ${filterStatus}` : ''}
            <span className="t-mute">▾</span>
          </button>
          {statusDropdown && (
            <div className="dropdown">
              {(['all', 'processing', 'indexed', 'partial_error', 'error'] as FilterStatus[]).map((s) => (
                <div
                  key={s}
                  className={`dropdown-item${filterStatus === s ? ' active' : ''}`}
                  onClick={() => { setFilterStatus(s); setPage(1); setStatusDropdown(false); }}
                >
                  {s === 'all' ? 'Todas' : s === 'processing' ? 'Procesando' : s === 'indexed' ? 'Lista' : s === 'partial_error' ? 'Parcial' : 'Error'}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex-1" />
        <span className="t-xs t-mute">
          {filtered.length} de {licitaciones.length}
        </span>

        <button className="btn sm ghost" onClick={exportCsv}>
          ⬇ Exportar CSV
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

        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 p-12">
            <div className="t-mute">
              {search ? `Sin resultados para "${search}"` : 'No hay licitaciones. Crea la primera.'}
            </div>
            {!search && (
              <button className="btn primary" onClick={() => navigate('/licitaciones/nueva')}>
                Nueva licitación
              </button>
            )}
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <table className="table compact rounded-none">
            <thead>
              <tr>
                <th className="w-8">
                  <input
                    type="checkbox"
                    checked={allSelectedOnPage}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className="w-[90px]">ID</th>
                <th>Título</th>
                <th className="w-[110px]">Estado</th>
                <th className="w-[80px] text-center">Docs</th>
                <th className="w-[160px]">Creada</th>
                <th className="w-7" />
              </tr>
            </thead>
            <tbody>
              {pageItems.map((l) => (
                <tr
                  key={l.id}
                  className={`cursor-pointer${selected.has(l.id) ? ' sel' : ''}`}
                  onClick={() => navigate(`/licitaciones/${l.id}`)}
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(l.id)}
                      onChange={() => toggleSelect(l.id)}
                    />
                  </td>
                  <td className="num t-mute text-11">
                    {shortId(l.id)}
                  </td>
                  <td>
                    <span className="t-medium text-12">
                      {l.title}
                    </span>
                    <div className="t-xs t-mute mono mt-0.5">{l.id}</div>
                  </td>
                  <td>
                    <StateTag status={l.status} />
                  </td>
                  <td className="text-center text-11 t-mute">
                    {docCountLabel(l)}
                  </td>
                  <td className="num t-mute text-11">
                    {formatDate(l.created_at)}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <button
                      className={`btn sm ghost danger px-[6px] py-[2px]${deleting === l.id ? ' opacity-50' : ''}`}
                      title="Eliminar licitación"
                      disabled={deleting === l.id}
                      onClick={() => handleDelete(l)}
                    >
                      {deleting === l.id ? '…' : '✕'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer / pagination */}
      {!loading && !error && filtered.length > 0 && (
        <div className="flex justify-between items-center px-3 py-2 border-t border-line bg-surface text-11 text-ink-3 shrink-0">
          <span>
            {selected.size > 0
              ? `${selected.size} seleccionadas · `
              : ''}
            {filtered.length} licitaciones
          </span>
          <div className="flex items-center gap-2">
            <span>
              {(page - 1) * rowsPerPage + 1}–
              {Math.min(page * rowsPerPage, filtered.length)} de {filtered.length}
            </span>
            <button
              className="btn sm ghost"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              ‹
            </button>
            <button
              className="btn sm ghost"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              ›
            </button>
          </div>
        </div>
      )}
    </AppShell>
  );
}
