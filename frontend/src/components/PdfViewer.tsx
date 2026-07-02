import { useEffect, useState } from 'react';
import { fetchDocumentViewUrl } from '../services/api';
import type { PliegoResponse } from '../types/licitacion';

export interface PdfViewerTarget {
  pliegoId: string;
  page?: number | null;
  filename?: string;
}

interface PdfViewerProps {
  licitacionId: string;
  documents: PliegoResponse[];
  target: PdfViewerTarget | null;
  onClose: () => void;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  pcap: 'PCAP',
  ppt: 'PPT',
  anexo: 'Anexo',
};

export default function PdfViewer({ licitacionId, documents, target, onClose }: PdfViewerProps) {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentDoc = target ? documents.find((d) => d.id === target.pliegoId) : null;

  useEffect(() => {
    if (!target) {
      setPdfUrl(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchDocumentViewUrl(licitacionId, target.pliegoId)
      .then((url) => {
        if (cancelled) return;
        const fullUrl = target.page ? `${url}#page=${target.page}` : url;
        setPdfUrl(fullUrl);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Error al cargar el documento');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [licitacionId, target?.pliegoId, target?.page]);

  if (!target) return null;

  return (
    <div className="flex flex-col border-l border-line bg-surface shrink-0" style={{ width: 'min(50vw, 700px)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-line shrink-0 bg-surface-2">
        <div className="flex flex-col min-w-0">
          <div className="text-12 font-medium truncate">
            {currentDoc ? (
              <>
                <span className="text-ink-4">{DOC_TYPE_LABELS[currentDoc.document_type] || currentDoc.document_type}</span>
                {' '}{currentDoc.filename}
              </>
            ) : (
              'Documento'
            )}
          </div>
          {target.page && (
            <div className="text-11 text-ink-4">Página {target.page}</div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {pdfUrl && (
            <button
              className="btn sm ghost text-11"
              onClick={() => window.open(pdfUrl, '_blank', 'noopener,noreferrer')}
              title="Abrir en nueva pestaña"
            >
              ↗
            </button>
          )}
          <button
            className="btn sm ghost text-11"
            onClick={onClose}
            title="Cerrar visor"
          >
            &times;
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface z-10">
            <div className="text-13 text-ink-4">Cargando documento…</div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface z-10 p-4">
            <div className="text-12 text-red-500 bg-red-50 border border-red-200 rounded px-3 py-2 max-w-sm text-center">
              {error}
            </div>
          </div>
        )}

        {pdfUrl && !error && (
          <iframe
            src={pdfUrl}
            className="w-full h-full border-0"
            title="Visor de documento"
          />
        )}
      </div>
    </div>
  );
}
