import { useEffect, useState } from 'react';
import EmptyState from '../../components/ui/EmptyState';
import { fetchRequirements } from '../../services/api';
import type { LicitacionResponse, RequirementsListResponse, RequirementResponse } from '../../types/licitacion';

interface RequisitosTabProps {
  licitacion: LicitacionResponse;
  onOpenDocument: (opts: { filename?: string; documentType?: string; page?: number | null }) => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  administrativo: 'Administrativos',
  solvencia_tecnica: 'Solvencia técnica',
  solvencia_economica: 'Solvencia económica',
  tecnico: 'Técnicos',
  criterio_adjudicacion: 'Criterios de adjudicación',
};

const CATEGORY_ORDER = [
  'administrativo',
  'solvencia_tecnica',
  'solvencia_economica',
  'tecnico',
  'criterio_adjudicacion',
];

const DOC_TYPE_LABELS: Record<string, string> = {
  pcap: 'PCAP',
  ppt: 'PPT',
  anexo: 'Anexo',
};

function groupByCategory(requirements: RequirementResponse[]): Record<string, RequirementResponse[]> {
  const groups: Record<string, RequirementResponse[]> = {};
  for (const req of requirements) {
    const cat = req.categoria;
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(req);
  }
  return groups;
}

export default function RequisitosTab({ licitacion, onOpenDocument }: RequisitosTabProps) {
  const [data, setData] = useState<RequirementsListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  const isReady = licitacion.status === 'indexed' || licitacion.status === 'partial_error';

  useEffect(() => {
    if (!isReady) return;
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetchRequirements(licitacion.id)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Error al extraer requisitos');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [licitacion.id, isReady]);

  function toggleCheck(id: string) {
    setChecked((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  if (!isReady) {
    return (
      <div className="page">
        <EmptyState
          title="Extracción de requisitos no disponible"
          description="La licitación debe estar completamente indexada antes de poder extraer requisitos."
          sprint={`Estado actual: ${licitacion.status}`}
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="page">
        <div className="t-up mb-4">Analizando el documento completo…</div>
        <div className="flex flex-col gap-3">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <div key={i} className="h-4 bg-surface-2 rounded animate-pulse" style={{ width: `${30 + i * 7}%` }} />
          ))}
        </div>
        <p className="text-12 text-ink-4 mt-4">
          Se analiza el documento completo para extraer todos los requisitos. Puede tardar hasta 30 segundos.
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <div className="text-13 text-red-500 bg-red-50 border border-red-200 rounded px-4 py-3">
          {error}
        </div>
      </div>
    );
  }

  if (!data || data.requirements.length === 0) {
    return (
      <div className="page">
        <EmptyState
          title="No se encontraron requisitos"
          description="No se pudieron extraer requisitos de los documentos de esta licitación."
        />
      </div>
    );
  }

  const grouped = groupByCategory(data.requirements);
  const totalObligatorios = data.requirements.filter((r) => r.es_obligatorio).length;
  const totalValorables = data.requirements.filter((r) => !r.es_obligatorio).length;
  const totalChecked = Object.values(checked).filter(Boolean).length;

  return (
    <div className="page overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="t-up">Checklist de requisitos</div>
          <p className="text-12 text-ink-4 mt-1">
            {data.requirements.length} requisitos — {totalObligatorios} obligatorios, {totalValorables} valorables
            {totalChecked > 0 && ` · ${totalChecked}/${data.requirements.length} marcados`}
            {data.cached && ' · cacheado'}
          </p>
        </div>
        {totalChecked > 0 && (
          <div className="text-12 text-ink-4">
            <div className="h-1.5 w-32 bg-surface-2 rounded-full overflow-hidden">
              <div
                className="h-full bg-green-500 rounded-full transition-all duration-300"
                style={{ width: `${(totalChecked / data.requirements.length) * 100}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Categories */}
      <div className="flex flex-col gap-6">
        {CATEGORY_ORDER.filter((cat) => grouped[cat]?.length).map((cat) => {
          const catReqs = grouped[cat];
          const catChecked = catReqs.filter((r) => checked[r.id]).length;

          return (
            <div key={cat}>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-13 font-medium text-ink-2">
                  {CATEGORY_LABELS[cat] || cat}
                </span>
                <span className="text-11 text-ink-4">
                  {catChecked}/{catReqs.length}
                </span>
              </div>

              <div className="flex flex-col gap-1">
                {catReqs.map((req) => {
                  const isChecked = !!checked[req.id];

                  return (
                    <div
                      key={req.id}
                      className={`flex items-start gap-3 px-3 py-2.5 rounded border transition-colors ${
                        isChecked
                          ? 'bg-green-50/50 border-green-200/60'
                          : 'bg-surface border-line hover:border-ink-5'
                      }`}
                    >
                      {/* Checkbox */}
                      <button
                        type="button"
                        className={`shrink-0 mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center transition-colors ${
                          isChecked
                            ? 'bg-green-500 border-green-500'
                            : 'border-ink-5 hover:border-ink-3'
                        }`}
                        onClick={() => toggleCheck(req.id)}
                      >
                        {isChecked && (
                          <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                            <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )}
                      </button>

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className={`text-13 leading-relaxed ${isChecked ? 'line-through text-ink-4' : ''}`}>
                          {req.descripcion}
                        </div>
                        <div className="flex items-center gap-2 mt-1 text-11 text-ink-4">
                          <span className={`inline-block w-1.5 h-1.5 rounded-full ${
                            req.es_obligatorio ? 'bg-red-400' : 'bg-blue-400'
                          }`} />
                          <span>{req.es_obligatorio ? 'Obligatorio' : 'Valorable'}</span>
                          <span>·</span>
                          <span>{DOC_TYPE_LABELS[req.documento_origen] || req.documento_origen}</span>
                          {req.pagina != null && (
                            <>
                              <span>·</span>
                              <button
                                className="text-accent hover:underline"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onOpenDocument({
                                    documentType: req.documento_origen,
                                    page: req.pagina,
                                  });
                                }}
                              >
                                p. {req.pagina} ↗
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
