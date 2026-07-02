import type { PliegoResponse } from '../types/licitacion';
import type { PdfViewerTarget } from '../components/PdfViewer';

/**
 * Resolves a document reference (by filename or document_type) into a PdfViewerTarget
 * that can be used to open the embedded PDF viewer at the correct page.
 */
export function resolveDocumentTarget(
  documents: PliegoResponse[],
  opts: {
    filename?: string;
    documentType?: string;
    page?: number | null;
  },
): PdfViewerTarget | null {
  const doc = findDocument(documents, opts);
  if (!doc) return null;

  return {
    pliegoId: doc.id,
    page: opts.page ?? null,
    filename: doc.filename,
  };
}

/**
 * Finds the matching document from the list by filename or document_type.
 */
function findDocument(
  documents: PliegoResponse[],
  opts: { filename?: string; documentType?: string },
): PliegoResponse | undefined {
  if (opts.filename) {
    const needle = opts.filename.toLowerCase();
    const byName = documents.find((d) => d.filename.toLowerCase() === needle);
    if (byName) return byName;
  }
  if (opts.documentType) {
    const needle = opts.documentType.toLowerCase();
    return documents.find((d) => d.document_type.toLowerCase() === needle);
  }
  return documents[0];
}
