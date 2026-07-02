import { useEffect, useState } from 'react';
import type { LicitacionResponse } from '../../types/licitacion';
import { fetchQueryHistory, fetchMemoriaChatHistory } from '../../services/api';

interface AuditoriaTabProps {
  licitacion: LicitacionResponse;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  pcap: 'PCAP',
  ppt: 'PPT',
  anexo: 'Anexo',
};

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('es-ES', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

interface AuditEvent {
  ts: string;
  actor: string;
  action: string;
  detail: string;
}

export default function AuditoriaTab({ licitacion }: AuditoriaTabProps) {
  const [asyncEvents, setAsyncEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    async function loadData() {
      try {
        const [queries, memChat] = await Promise.all([
          fetchQueryHistory(licitacion.id).catch(() => []),
          fetchMemoriaChatHistory(licitacion.id).catch(() => [])
        ]);

        if (!active) return;

        const newEvents: AuditEvent[] = [];

        queries.forEach(q => {
          newEvents.push({
            ts: q.created_at,
            actor: licitacion.user_id,
            action: 'Consulta RAG',
            detail: `Pregunta: ${q.question.length > 80 ? q.question.substring(0, 80) + '...' : q.question}`
          });
        });

        memChat.forEach(m => {
          newEvents.push({
            ts: m.created_at,
            actor: m.role === 'user' ? licitacion.user_id : 'Asistente IA',
            action: m.role === 'user' ? 'Mensaje en Memoria' : 'Respuesta (Memoria)',
            detail: m.content.length > 80 ? m.content.substring(0, 80) + '...' : m.content
          });
        });

        setAsyncEvents(newEvents);
      } catch (err) {
        console.error("Error cargando auditoria:", err);
      } finally {
        if (active) setLoading(false);
      }
    }

    loadData();

    return () => { active = false; };
  }, [licitacion.id, licitacion.user_id]);

  const baseEvents: AuditEvent[] = [
    {
      ts: licitacion.created_at,
      actor: licitacion.user_id,
      action: 'Licitación creada',
      detail: `Título: ${licitacion.title} — ${licitacion.documents.length} documento(s)`,
    },
    ...licitacion.documents.map((doc) => ({
      ts: doc.uploaded_at,
      actor: doc.user_id,
      action: `Documento subido (${DOC_TYPE_LABELS[doc.document_type] || doc.document_type})`,
      detail: `Archivo: ${doc.filename} (${(doc.size_bytes / 1024).toFixed(0)} KB)`,
    })),
    ...licitacion.documents
      .filter((doc) => doc.processed_at)
      .map((doc) => ({
        ts: doc.processed_at!,
        actor: 'pipeline v0.4.2',
        action: doc.status === 'indexed'
          ? `Procesamiento completado (${DOC_TYPE_LABELS[doc.document_type] || doc.document_type})`
          : `Procesamiento fallido (${DOC_TYPE_LABELS[doc.document_type] || doc.document_type})`,
        detail: doc.status === 'indexed'
          ? `OCR + chunking + indexación completados para ${doc.filename}.`
          : `Error en el pipeline de procesamiento de ${doc.filename}.`,
      })),
  ];

  const events = [...baseEvents, ...asyncEvents].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());

  return (
    <div className="page">
      <div className="flex gap-3 items-start">
        <div className="flex flex-col flex-1 gap-3">
          <div className="surface">
            <div className="flex justify-between items-center p-3 border-b border-line">
              <div className="t-medium">Registro de eventos</div>
              <span className="tag">{events.length} eventos</span>
            </div>
            <table className="table compact">
              <thead>
                <tr>
                  <th className="w-[160px]">Fecha y hora</th>
                  <th className="w-[140px]">Actor</th>
                  <th className="w-[250px]">Acción</th>
                  <th>Detalle</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={4} className="text-center p-4 t-mute">
                      Cargando historial completo...
                    </td>
                  </tr>
                ) : events.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="text-center p-4 t-mute">
                      No hay eventos registrados.
                    </td>
                  </tr>
                ) : (
                  events.map((ev, i) => (
                    <tr key={i}>
                      <td className="num t-mute text-11">
                        {formatDate(ev.ts)}
                      </td>
                      <td className="mono text-11 text-ink-2 truncate max-w-[140px]" title={ev.actor}>
                        {ev.actor}
                      </td>
                      <td className="t-medium text-12">
                        {ev.action}
                      </td>
                      <td className="t-mute text-12 max-w-[400px] truncate" title={ev.detail}>
                        {ev.detail}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
