import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import { Previewer } from 'pagedjs';

import pagedCssUrl from '../lib/memoriaPaged.css?url';
import { normalizeDocumentMarkdown } from '../utils/documentMarkdown';
import '../lib/memoriaPagedViewer.css';

/**
 * Render Markdown como hojas A4 paginadas (paged.js).
 *
 * El usuario ve el documento separado en páginas, con el mismo CSS (@page A4 +
 * tipografía) que WeasyPrint aplica al exportar a PDF — lo que se ve es lo que
 * se exporta. Ver `frontend/src/lib/memoriaPaged.css` para las reglas y su
 * gemelo en `backend/app/services/memoria_export.py`.
 */
export default function PaginatedMarkdown({ markdown }: { markdown: string }) {
  const sourceRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<HTMLDivElement>(null);
  // Paginación en vuelo: encadenamos para evitar que dos `preview()` escriban
  // el mismo target en paralelo (StrictMode doble-invoca el efecto en dev y
  // produciría contenido duplicado).
  const pendingRef = useRef<Promise<unknown> | null>(null);
  const [paginating, setPaginating] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sourceRef.current || !targetRef.current) return;
    let cancelled = false;

    setPaginating(true);
    setError(null);

    const source = document.createElement('div');
    source.innerHTML = sourceRef.current.innerHTML;
    const runningElements = Array.from(
      source.querySelectorAll('.document-header, .document-footer')
    );
    runningElements.reverse().forEach(element => source.prepend(element));
    const html = source.innerHTML;
    const target = targetRef.current;

    const run = async () => {
      // Espera a que termine la paginación anterior antes de tocar el DOM.
      if (pendingRef.current) {
        try { await pendingRef.current; } catch { /* ignorado: ya lo gestionó su propio handler */ }
      }
      if (cancelled) return;

      target.innerHTML = '';
      const previewer = new Previewer();
      const promise = previewer.preview(html, [pagedCssUrl], target);
      pendingRef.current = promise;

      try {
        await promise;
        if (!cancelled) setPaginating(false);
      } catch (err) {
        console.error('paged.js error', err);
        if (!cancelled) {
          setError('No se pudo paginar el documento.');
          setPaginating(false);
        }
      } finally {
        if (pendingRef.current === promise) pendingRef.current = null;
      }
    };

    run();

    return () => {
      cancelled = true;
    };
  }, [markdown]);

  return (
    <div className="memoria-paged-viewer relative">
      {/* Fuente oculta: ReactMarkdown renderiza aquí y leemos el HTML. */}
      <div
        ref={sourceRef}
        aria-hidden
        style={{ position: 'absolute', left: '-99999px', top: 0, width: 0, height: 0, overflow: 'hidden' }}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
          {normalizeDocumentMarkdown(markdown)}
        </ReactMarkdown>
      </div>

      {paginating && (
        <div className="memoria-paged-viewer__empty">Paginando documento…</div>
      )}
      {error && !paginating && (
        <div className="memoria-paged-viewer__empty">{error}</div>
      )}

      <div ref={targetRef} />
    </div>
  );
}
