import type { LicitacionResponse } from '../../types/licitacion';
import StateTag from '../../components/ui/StateTag';
import { deleteLicitacion, fetchDocumentViewUrl } from '../../services/api';
import { useNavigate } from 'react-router-dom';
import { useModal } from '../../hooks/useModal';

interface DocumentoTabProps {
  licitacion: LicitacionResponse;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  pcap: 'PCAP',
  ppt: 'PPT',
  anexo: 'Anexo',
};

function formatBytes(b: number): string {
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / 1024 / 1024).toFixed(2)} MB`;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('es-ES', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function DocumentoTab({ licitacion }: DocumentoTabProps) {
  const navigate = useNavigate();
  const { showModal } = useModal();

  async function handleCopyId() {
    try {
      await navigator.clipboard.writeText(licitacion.id);
      await showModal({
        type: 'alert',
        title: 'ID copiado',
        description: <span className="font-mono break-all">{licitacion.id}</span>,
        tone: 'success',
      });
    } catch {
      await showModal({
        type: 'alert',
        title: 'No se pudo copiar el ID',
        description: 'El navegador no ha permitido acceder al portapapeles.',
        tone: 'danger',
      });
    }
  }

  async function handleOpenDocument(docId: string) {
    // Open the tab synchronously so the popup blocker treats it as a user
    // gesture; the SAS URL is fetched async and assigned afterwards. We can't
    // pass `noopener` here because it nulls the returned handle.
    const win = window.open('about:blank', '_blank');
    try {
      const url = await fetchDocumentViewUrl(licitacion.id, docId);
      if (win) win.location.href = url;
      else window.open(url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      if (win) win.close();
      await showModal({
        type: 'alert',
        title: 'No se pudo abrir el documento',
        description: err instanceof Error ? err.message : String(err),
        tone: 'danger',
      });
    }
  }

  function handleExportMetadata() {
    const data = JSON.stringify(licitacion, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${licitacion.id.slice(0, 8)}_licitacion_metadata.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleDelete() {
    const confirmed = await showModal({
      type: 'confirmation',
      title: 'Eliminar licitación',
      description: 'Se eliminarán permanentemente la licitación y todos sus documentos.',
      tone: 'danger',
      confirmLabel: 'Eliminar',
    });
    if (!confirmed) return;

    try {
      await deleteLicitacion(licitacion.id);
      navigate('/licitaciones');
    } catch (err) {
      await showModal({
        type: 'alert',
        title: 'No se pudo eliminar la licitación',
        description: err instanceof Error ? err.message : String(err),
        tone: 'danger',
      });
    }
  }

  const totalSize = licitacion.documents.reduce((sum, d) => sum + d.size_bytes, 0);

  return (
    <div className="page">
      <div className="flex gap-3 items-start">
        {/* Main document info */}
        <div className="flex flex-col flex-1 gap-3">
          {/* Licitacion metadata */}
          <div className="surface">
            <div className="flex items-center gap-3 p-3 border-b border-line bg-surface-2">
              <span className="icn-doc w-6 h-7" />
              <div className="flex flex-col flex-1">
                <div className="t-medium">{licitacion.title}</div>
                <div className="t-xs t-mute">
                  {licitacion.documents.length} documento{licitacion.documents.length !== 1 ? 's' : ''} · {formatBytes(totalSize)} total
                </div>
              </div>
              <StateTag status={licitacion.status} />
            </div>

            <div className="p-4">
              <div className="t-up mb-3">Metadatos de la licitación</div>
              <div className="grid grid-cols-2 gap-3">
                {[
                  ['ID de licitación', licitacion.id, true],
                  ['Título', licitacion.title, false],
                  ['Propietario', licitacion.user_id, false],
                  ['Estado', licitacion.status, false],
                  ['Documentos', `${licitacion.documents.length}`, false],
                  ['Tamaño total', formatBytes(totalSize), false],
                  ['Creada', formatDate(licitacion.created_at), false],
                  ['Actualizada', formatDate(licitacion.updated_at), false],
                ].map(([k, v, mono]) => (
                  <div
                    key={String(k)}
                    className="flex flex-col gap-1 border-t border-line pt-2"
                  >
                    <span className="label">{k}</span>
                    <span className={`text-12 break-all text-ink-2${mono ? ' mono' : ''}`}>
                      {String(v) || '—'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex justify-between items-center p-3 border-t border-line">
              <span className="help">
                Procesamiento gestionado por pipeline v0.4.2 (Azure Document Intelligence + AI Search)
              </span>
              <div className="flex gap-2">
                <button className="btn sm ghost" onClick={handleCopyId}>
                  Copiar ID
                </button>
                <button className="btn sm" onClick={handleExportMetadata}>
                  Exportar metadatos JSON
                </button>
              </div>
            </div>
          </div>

          {/* Documents list */}
          <div className="surface">
            <div className="p-3 border-b border-line">
              <div className="t-medium">Documentos de la licitación</div>
            </div>
            <table className="table compact">
              <thead>
                <tr>
                  <th className="w-[80px]">Tipo</th>
                  <th>Título</th>
                  <th>Archivo</th>
                  <th className="w-[100px]">Estado</th>
                  <th className="w-[100px] text-right">Tamaño</th>
                  <th className="w-[160px]">Subido</th>
                  <th className="w-[60px]" />
                </tr>
              </thead>
              <tbody>
                {licitacion.documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>
                      <span className="tag text-10">
                        {DOC_TYPE_LABELS[doc.document_type] || doc.document_type}
                      </span>
                    </td>
                    <td>
                      {doc.doc_title ? (
                        <span className="text-12">{doc.doc_title}</span>
                      ) : (
                        <span className="t-mute text-12">—</span>
                      )}
                    </td>
                    <td>
                      <div className="t-medium text-12">{doc.filename}</div>
                      <div className="t-xs t-mute mono">{doc.id.slice(0, 8).toUpperCase()}</div>
                    </td>
                    <td>
                      <StateTag status={doc.status} />
                    </td>
                    <td className="num text-right text-11 text-ink-3">
                      {formatBytes(doc.size_bytes)}
                    </td>
                    <td className="num t-mute text-11">
                      {formatDate(doc.uploaded_at)}
                    </td>
                    <td>
                      <button
                        className="btn sm ghost px-[6px] py-[2px]"
                        title="Ver / descargar original"
                        onClick={() => void handleOpenDocument(doc.id)}
                      >
                        ↗
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Processing info */}
          <div className="surface">
            <div className="p-3 border-b border-line">
              <div className="t-medium">Estado del procesamiento</div>
            </div>
            <div className="p-3 flex flex-col gap-2 text-12">
              {licitacion.documents.map((doc) => {
                const steps = [
                  [
                    `OCR — ${DOC_TYPE_LABELS[doc.document_type]} (${doc.filename})`,
                    doc.status === 'indexed' ? 'Completado' : doc.status === 'processing' ? 'En proceso' : doc.status === 'error' ? 'Error' : 'Pendiente',
                    doc.status === 'indexed' ? 'ok' : doc.status === 'error' ? 'err' : 'idle',
                  ],
                  [
                    `Indexación — ${DOC_TYPE_LABELS[doc.document_type]}`,
                    doc.status === 'indexed' ? 'Completado' : 'Pendiente',
                    doc.status === 'indexed' ? 'ok' : 'idle',
                  ],
                ];
                return steps.map(([k, v, s]) => (
                  <div key={String(k)} className="flex justify-between items-center">
                    <span className="t-mute">{k}</span>
                    <span className="flex items-center gap-2">
                      <span className={`dot ${s}`} />
                      <span>{v}</span>
                    </span>
                  </div>
                ));
              })}
            </div>
          </div>
        </div>

        {/* Right: actions */}
        <div className="flex flex-col w-[300px] gap-3 shrink-0">
          <div className="surface">
            <div className="p-3 border-b border-line">
              <div className="t-medium">Acciones</div>
            </div>
            <div className="flex flex-col gap-1 p-3">
              {licitacion.documents.map((doc) => (
                <button
                  key={doc.id}
                  className="btn w-full justify-start"
                  onClick={() => void handleOpenDocument(doc.id)}
                >
                  Descargar {DOC_TYPE_LABELS[doc.document_type]} — {doc.filename.length > 25 ? doc.filename.slice(0, 25) + '…' : doc.filename}
                </button>
              ))}
              <button
                className="btn w-full justify-start"
                onClick={handleExportMetadata}
              >
                Exportar metadatos JSON
              </button>
              <button
                className="btn w-full justify-start"
                title="Generar propuesta — pendiente de implementación"
                onClick={() => void showModal({
                  type: 'alert',
                  title: 'Función no disponible',
                  description: 'La generación de propuesta está pendiente de implementación.',
                  tone: 'info',
                })}
              >
                Generar borrador de propuesta
              </button>
              <button
                className="btn danger w-full justify-start mt-1"
                onClick={handleDelete}
              >
                Eliminar licitación
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
