import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import AppShell from '../components/layout/AppShell';
import StateTag from '../components/ui/StateTag';
import CommercialStateBadge from '../components/ui/CommercialStateBadge';
import CommercialStateEditor from '../components/ui/CommercialStateEditor';
import PdfViewer from '../components/PdfViewer';
import type { PdfViewerTarget } from '../components/PdfViewer';
import { fetchLicitacion } from '../services/api';
import type { LicitacionResponse, TabKey } from '../types/licitacion';
import { resolveDocumentTarget } from '../utils/documentLink';

import ResumenTab from './detail/ResumenTab';
import ChatTab from './detail/ChatTab';
import RequisitosTab from './detail/RequisitosTab';
import MatchScoreTab from './detail/MatchScoreTab';
import MemoriaTab from './detail/MemoriaTab';
import DocumentoTab from './detail/DocumentoTab';
import AuditoriaTab from './detail/AuditoriaTab';

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('es-ES', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function formatBytes(b: number): string {
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

const TABS: { key: TabKey; label: string }[] = [
  { key: 'resumen', label: 'Resumen' },
  { key: 'chat', label: 'Consultas' },
  { key: 'requisitos', label: 'Requisitos' },
  { key: 'match', label: 'Match score' },
  { key: 'memoria', label: 'Memoria' },
  { key: 'documento', label: 'Documentos' },
  { key: 'auditoria', label: 'Auditoría' },
];

const DOC_TYPE_LABELS: Record<string, string> = {
  pcap: 'PCAP',
  ppt: 'PPT',
  anexo: 'Anexo',
};

export default function LicitacionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = (searchParams.get('tab') as TabKey) || 'resumen';

  const [licitacion, setLicitacion] = useState<LicitacionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pdfTarget, setPdfTarget] = useState<PdfViewerTarget | null>(null);

  const onOpenDocument = useCallback(
    (opts: { filename?: string; documentType?: string; page?: number | null }) => {
      if (!licitacion) return;
      const target = resolveDocumentTarget(licitacion.documents, opts);
      if (target) setPdfTarget(target);
    },
    [licitacion],
  );

  function setTab(key: TabKey) {
    setSearchParams({ tab: key });
  }

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    fetchLicitacion(id)
      .then((l) => { setLicitacion(l); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  // Poll while processing
  useEffect(() => {
    if (!licitacion || licitacion.status === 'indexed' || licitacion.status === 'error') return;
    const interval = setInterval(async () => {
      try {
        const updated = await fetchLicitacion(licitacion.id);
        setLicitacion(updated);
      } catch {
        // silently ignore poll errors
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [licitacion]);

  if (loading) {
    return (
      <AppShell crumbs={['Licitaciones', '…']}>
        <div className="flex items-center justify-center flex-1 text-ink-3">
          Cargando licitación…
        </div>
      </AppShell>
    );
  }

  if (error || !licitacion) {
    return (
      <AppShell crumbs={['Licitaciones', 'Error']}>
        <div className="flex flex-col items-center justify-center gap-2 flex-1 p-12">
          <div className="tag err">Error</div>
          <div className="help">{error ?? 'Licitación no encontrada'}</div>
          <button className="btn" onClick={() => navigate('/licitaciones')}>
            ← Volver a licitaciones
          </button>
        </div>
      </AppShell>
    );
  }

  const shortId = licitacion.id.slice(0, 8).toUpperCase();
  const totalSize = licitacion.documents.reduce((sum, d) => sum + d.size_bytes, 0);

  return (
    <AppShell crumbs={['Licitaciones', shortId]}>
      <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
        {/* Licitacion header */}
        <div className="flex items-center justify-between px-4 py-3 bg-surface border-b border-line shrink-0 gap-4">
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2">
              <span className="num t-mute t-sm">{shortId}</span>
              <StateTag status={licitacion.status} />
              <CommercialStateBadge estado={licitacion.estado} resultado={licitacion.resultado} />
              <span className="t-xs t-mute">{formatBytes(totalSize)}</span>
              <span className="t-xs t-mute">· {licitacion.documents.length} documento{licitacion.documents.length !== 1 ? 's' : ''}</span>
            </div>
            <div className="t-2xl mt-1 truncate">
              {licitacion.title}
            </div>
            <div className="t-xs t-mute mt-1 flex items-center gap-2 flex-wrap">
              <span>Propietario: {licitacion.user_id}</span>
              <span>·</span>
              <span>Creada: {formatDate(licitacion.created_at)}</span>
              <span>·</span>
              <span>Actualizada: {formatDate(licitacion.updated_at)}</span>
            </div>
            {/* Document badges */}
            <div className="flex items-center gap-2 mt-2">
              {licitacion.documents.map((doc) => (
                <span
                  key={doc.id}
                  className="tag text-10"
                  title={`${doc.filename} (${doc.status})`}
                >
                  <span className={`dot ${doc.status === 'indexed' ? 'ok' : doc.status === 'error' ? 'err' : 'proc'}`} />
                  {DOC_TYPE_LABELS[doc.document_type] || doc.document_type}
                  <span className="t-mute ml-1">{doc.filename.length > 20 ? doc.filename.slice(0, 20) + '…' : doc.filename}</span>
                </span>
              ))}
            </div>
          </div>

          <div className="flex gap-3 items-center shrink-0">
            <CommercialStateEditor licitacion={licitacion} onUpdated={setLicitacion} />
            <button
              className="btn sm"
              onClick={() => {
                const data = JSON.stringify(licitacion, null, 2);
                const blob = new Blob([data], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${shortId}_licitacion.json`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              Exportar
            </button>
          </div>
        </div>

        {/* Partial error warning */}
        {licitacion.status === 'partial_error' && (
          <div className="px-4 py-2 bg-yellow-50 border-b border-yellow-200 flex items-center gap-2 text-12 shrink-0">
            <span className="dot warn" />
            <span>
              Algunos documentos no se pudieron procesar correctamente. Las funciones de resumen, consulta y match están disponibles con los documentos indexados.
            </span>
          </div>
        )}

        {/* Tab navigation */}
        <div className="navbar">
          {TABS.map(({ key, label }) => (
            <div
              key={key}
              className={`item${tabParam === key ? ' active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label}
            </div>
          ))}
        </div>

        {/* Tab content + PDF viewer */}
        <div className="flex flex-1 min-h-0">
          <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
            {tabParam === 'resumen'    && <ResumenTab licitacion={licitacion} />}
            {tabParam === 'chat'       && <ChatTab licitacion={licitacion} onOpenDocument={onOpenDocument} />}
            {tabParam === 'requisitos' && <RequisitosTab licitacion={licitacion} onOpenDocument={onOpenDocument} />}
            {tabParam === 'match'      && <MatchScoreTab licitacion={licitacion} onOpenDocument={onOpenDocument} />}
            {tabParam === 'memoria'    && <MemoriaTab licitacion={licitacion} />}
            {tabParam === 'documento'  && <DocumentoTab licitacion={licitacion} />}
            {tabParam === 'auditoria'  && <AuditoriaTab licitacion={licitacion} />}
          </div>
          <PdfViewer
            licitacionId={licitacion.id}
            documents={licitacion.documents}
            target={pdfTarget}
            onClose={() => setPdfTarget(null)}
          />
        </div>
      </div>
    </AppShell>
  );
}
