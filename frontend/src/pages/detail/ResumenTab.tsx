import { useState, useEffect } from 'react';
import EmptyState from '../../components/ui/EmptyState';
import { fetchSummary } from '../../services/api';
import type { LicitacionResponse, SummaryResponse } from '../../types/licitacion';

interface ResumenTabProps {
  licitacion: LicitacionResponse;
}

export default function ResumenTab({ licitacion }: ResumenTabProps) {
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isReady = licitacion.status === 'indexed' || licitacion.status === 'partial_error';

  useEffect(() => {
    if (!isReady) return;

    setLoading(true);
    setError(null);
    fetchSummary(licitacion.id)
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : 'Error al generar resumen'))
      .finally(() => setLoading(false));
  }, [licitacion.id, licitacion.status, isReady]);

  if (!isReady) {
    return (
      <div className="page">
        <EmptyState
          title="Resumen no disponible"
          description={
            licitacion.status === 'error'
              ? 'El procesamiento de la licitación terminó con error. El resumen ejecutivo no puede generarse.'
              : 'La licitación está siendo procesada con OCR e indexación. El resumen estará disponible cuando finalice.'
          }
          sprint={`Estado actual: ${licitacion.status}`}
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="page">
        <div className="flex flex-col gap-4">
          <div className="t-up">Generando resumen ejecutivo…</div>
          <div className="flex flex-col gap-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-4 bg-surface-2 rounded animate-pulse" style={{ width: `${60 + i * 8}%` }} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <EmptyState
          title="Error al generar resumen"
          description={error}
        />
      </div>
    );
  }

  if (!summary) return null;

  return (
    <div className="page">
      <div className="flex flex-col gap-6">
        {/* Resumen general */}
        <section>
          <div className="t-up mb-2">Resumen ejecutivo</div>
          <div className="surface p-4 text-13 leading-relaxed">{summary.resumen}</div>
        </section>

        {/* Grid de datos clave */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Objeto */}
          <section className="surface p-4">
            <div className="t-up mb-2">Objeto del contrato</div>
            <div className="text-13">{summary.objeto}</div>
          </section>

          {/* Presupuesto y plazo */}
          <section className="surface p-4">
            <div className="t-up mb-2">Datos económicos y temporales</div>
            <div className="flex flex-col gap-2 text-13">
              <div className="flex justify-between">
                <span className="text-ink-3">Presupuesto</span>
                <span className="t-medium">{summary.presupuesto ?? 'No especificado'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-3">Plazo de ejecución</span>
                <span className="t-medium">{summary.plazo_ejecucion ?? 'No especificado'}</span>
              </div>
            </div>
          </section>
        </div>

        {/* Listas de requisitos */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ListSection title="Solvencia técnica" items={summary.solvencia_tecnica} />
          <ListSection title="Solvencia económica" items={summary.solvencia_economica} />
          <ListSection title="Criterios de adjudicación" items={summary.criterios_adjudicacion} />
          <ListSection title="Plazos clave" items={summary.plazos_clave} />
        </div>
      </div>
    </div>
  );
}

function ListSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;

  return (
    <section className="surface p-4">
      <div className="t-up mb-2">{title}</div>
      <ul className="flex flex-col gap-1 text-13">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-ink-4 shrink-0">-</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
