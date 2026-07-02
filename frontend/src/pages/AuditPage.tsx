import { useEffect, useState } from 'react';
import AppShell from '../components/layout/AppShell';
import { fetchSystemAudit, type AuditResponse } from '../services/api';

function fmt(n: number): string {
  return n.toLocaleString('es-ES');
}

const STATUS_LABELS: Record<string, string> = {
  processing: 'Procesando',
  indexed: 'Indexada',
  partial_error: 'Error parcial',
  error: 'Error',
};

const STATUS_TAG_CLASS: Record<string, string> = {
  processing: 'info',
  indexed: 'ok',
  partial_error: 'warn',
  error: 'err',
};

const DOC_TYPE_LABELS: Record<string, string> = {
  pcap: 'PCAP',
  ppt: 'PPT',
  anexo: 'Anexo',
};

export default function AuditPage() {
  const [data, setData] = useState<AuditResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchSystemAudit();
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error desconocido');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <AppShell crumbs={['Auditoría']}>
      <div className="page">
        {loading && (
          <div className="flex items-center justify-center p-12">
            <span className="t-mute">Cargando auditoría…</span>
          </div>
        )}

        {error && !loading && (
          <div className="flex flex-col items-center justify-center gap-2 p-12">
            <div className="tag err">Error de conexión</div>
            <div className="help text-center">{error}</div>
            <button className="btn sm" onClick={load}>Reintentar</button>
          </div>
        )}

        {!loading && !error && data && <AuditContent data={data} onRefresh={load} />}
      </div>
    </AppShell>
  );
}

function AuditContent({ data, onRefresh }: { data: AuditResponse; onRefresh: () => void }) {
  const { licitaciones, documents, memorias, ai_usage, users, user_activity } = data;

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="t-up mb-1">Auditoría general</div>
          <div className="help">
            Snapshot generado el{' '}
            {new Date(data.generated_at).toLocaleString('es-ES', {
              dateStyle: 'long',
              timeStyle: 'short',
            })}
          </div>
        </div>
        <button className="btn sm" onClick={onRefresh}>Actualizar</button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-5 gap-3">
        <KpiCard label="Licitaciones" value={fmt(licitaciones.total)} sub={`+${licitaciones.created_last_7d} en 7d`} />
        <KpiCard label="Documentos" value={fmt(documents.total_pliegos)} sub={`${documents.total_size_mb} MB`} />
        <KpiCard label="Páginas procesadas" value={fmt(documents.total_pages)} sub={`${fmt(documents.total_pliegos)} docs`} />
        <KpiCard label="Memorias" value={fmt(memorias.total_documents)} sub={`${fmt(memorias.total_chat_messages)} msgs chat`} />
        <KpiCard label="Consultas IA" value={fmt(ai_usage.total_queries)} sub={`${ai_usage.queries_last_7d} en 7d · ${ai_usage.queries_last_30d} en 30d`} />
      </div>

      {/* Two-column: Status + Docs */}
      <div className="grid grid-cols-2 gap-3">
        {/* Licitaciones by status */}
        <section className="surface p-4">
          <div className="t-up mb-3">Estado de licitaciones</div>
          <div className="flex flex-wrap gap-2 mb-3">
            {Object.entries(licitaciones.by_status).map(([status, count]) => (
              <span key={status} className={`tag ${STATUS_TAG_CLASS[status] ?? ''}`}>
                <span className={`dot ${STATUS_TAG_CLASS[status] ?? 'idle'}`} />
                {STATUS_LABELS[status] ?? status}: {fmt(count)}
              </span>
            ))}
          </div>
          <div className="flex gap-4">
            {Object.entries(licitaciones.by_status).map(([status, count]) => {
              const pct = licitaciones.total > 0 ? (count / licitaciones.total) * 100 : 0;
              return (
                <div key={status} className="flex-1">
                  <div className="progress-track">
                    <div
                      className="progress-fill"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: `var(--${STATUS_TAG_CLASS[status] ?? 'ink-4'})`,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="help mt-3">
            Últimos 7 días: <span className="t-medium">{licitaciones.created_last_7d}</span>
            {' · '}Últimos 30 días: <span className="t-medium">{licitaciones.created_last_30d}</span>
          </div>
        </section>

        {/* Documents + Memorias */}
        <section className="surface p-4">
          <div className="t-up mb-3">Documentos y memorias</div>
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <div className="text-11 t-mute t-bold uppercase tracking-label">Pliegos</div>
              {Object.entries(documents.by_type).map(([type, count]) => (
                <Row key={type} label={DOC_TYPE_LABELS[type] ?? type} value={fmt(count)} />
              ))}
              <div className="divider" />
              <Row label="Páginas totales" value={fmt(documents.total_pages)} />
              <Row label="Almacenamiento" value={`${documents.total_size_mb} MB`} />
            </div>
            <div className="flex flex-col gap-2">
              <div className="text-11 t-mute t-bold uppercase tracking-label">Memorias técnicas</div>
              <Row label="Documentos" value={fmt(memorias.total_documents)} />
              <Row label="Mensajes chat" value={fmt(memorias.total_chat_messages)} />
              <Row label="Plantillas ref." value={fmt(memorias.total_templates)} />
            </div>
          </div>
        </section>
      </div>

      {/* User activity table */}
      <section>
        <div className="flex items-center gap-2 mb-2">
          <div className="t-up">Actividad por usuario</div>
          <span className="tag">
            {users.total_users} usuarios · {users.active_users} activos
          </span>
        </div>

        <table className="table compact">
          <thead>
            <tr>
              <th>Usuario</th>
              <th className="text-right">Licitaciones</th>
              <th className="text-right">Consultas IA</th>
            </tr>
          </thead>
          <tbody>
            {user_activity.map((u) => (
              <tr key={u.user_id}>
                <td>
                  <span className="t-medium text-12">{u.full_name ?? '—'}</span>
                  <div className="help mono mt-0.5">{u.email}</div>
                </td>
                <td className="text-right num">{fmt(u.licitaciones_count)}</td>
                <td className="text-right num">{fmt(u.queries_count)}</td>
              </tr>
            ))}
            {user_activity.length === 0 && (
              <tr>
                <td colSpan={3} className="text-center t-mute py-6">
                  Sin usuarios registrados.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}


/* ── Tiny helper components using app design tokens ───────────── */

function KpiCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="surface-2 px-4 py-3">
      <div className="text-16 font-semibold tnum">{value}</div>
      <div className="help mt-0.5">{label}</div>
      {sub && <div className="t-xs t-mute mt-0.5">{sub}</div>}
    </div>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-12 t-mute">{label}</span>
      <span className="text-12 tnum t-medium">{value}</span>
    </div>
  );
}
