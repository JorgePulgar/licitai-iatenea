import { useEffect, useState } from 'react';
import EmptyState from '../../components/ui/EmptyState';
import { matchScore, fetchCompanyProfile, fetchCachedMatch } from '../../services/api';
import type { LicitacionResponse, MatchResponse, CompanyProfileResponse, RequirementMatch } from '../../types/licitacion';

interface MatchScoreTabProps {
  licitacion: LicitacionResponse;
  onOpenDocument: (opts: { filename?: string; documentType?: string; page?: number | null }) => void;
}

const ESTADO_CONFIG = {
  cumplido: { label: 'Cumplido', dot: 'bg-green-500', bg: 'bg-green-50 border-green-200', text: 'text-green-700' },
  no_cumplido: { label: 'No cumplido', dot: 'bg-red-400', bg: 'bg-red-50 border-red-200', text: 'text-red-600' },
  indeterminado: { label: 'Indeterminado', dot: 'bg-yellow-400', bg: 'bg-yellow-50 border-yellow-200', text: 'text-yellow-700' },
} as const;

function groupReqsByEstado(reqs: RequirementMatch[]) {
  const cumplidos = reqs.filter((r) => r.estado === 'cumplido');
  const no_cumplidos = reqs.filter((r) => r.estado === 'no_cumplido');
  const indeterminados = reqs.filter((r) => r.estado === 'indeterminado');
  return { cumplidos, no_cumplidos, indeterminados };
}

export default function MatchScoreTab({ licitacion, onOpenDocument }: MatchScoreTabProps) {
  const [result, setResult] = useState<MatchResponse | null>(null);
  const [profile, setProfile] = useState<CompanyProfileResponse | null>(null);
  const [profileMissing, setProfileMissing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const isReady = licitacion.status === 'indexed' || licitacion.status === 'partial_error';

  // Check if profile exists + load cached match result
  useEffect(() => {
    if (!isReady) return;
    let cancelled = false;

    async function init() {
      try {
        const p = await fetchCompanyProfile();
        if (!cancelled) setProfile(p);

        // Try to load cached match result
        const cached = await fetchCachedMatch(licitacion.id);
        if (!cancelled && cached) setResult(cached);
      } catch {
        if (!cancelled) setProfileMissing(true);
      } finally {
        if (!cancelled) setInitialLoading(false);
      }
    }

    init();
    return () => { cancelled = true; };
  }, [licitacion.id, isReady]);

  if (!isReady) {
    return (
      <div className="page">
        <EmptyState
          title="Match score no disponible"
          description="La licitación debe estar completamente indexada antes de calcular el match score."
          sprint={`Estado actual: ${licitacion.status}`}
        />
      </div>
    );
  }

  if (initialLoading) {
    return (
      <div className="page">
        <div className="flex flex-col gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-4 bg-surface-2 rounded animate-pulse" style={{ width: `${40 + i * 15}%` }} />
          ))}
        </div>
      </div>
    );
  }

  if (profileMissing) {
    return (
      <div className="page">
        <EmptyState
          title="Perfil de empresa no configurado"
          description="Para calcular el match score necesitas configurar primero tu perfil de empresa con las certificaciones, experiencia y datos de solvencia."
        />
        <div className="mt-4 flex justify-center">
          <a href="/settings" className="btn primary">
            Configurar perfil de empresa
          </a>
        </div>
      </div>
    );
  }

  async function handleCalculate() {
    setLoading(true);
    setError(null);
    try {
      const res = await matchScore(licitacion.id);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al calcular match score');
    } finally {
      setLoading(false);
    }
  }

  function scoreColor(score: number): string {
    if (score >= 7) return 'text-green-600';
    if (score >= 4) return 'text-yellow-600';
    return 'text-red-500';
  }

  function nivelColor(nivel: string): string {
    if (nivel === 'Alto') return 'bg-green-100 text-green-700 border-green-200';
    if (nivel === 'Medio') return 'bg-yellow-50 text-yellow-700 border-yellow-200';
    return 'bg-red-50 text-red-600 border-red-200';
  }

  return (
    <div className="page">
      {/* Profile summary + calculate button */}
      {!result && !loading && profile && (
        <div className="flex flex-col items-center gap-4 py-8">
          <div className="text-center">
            <div className="text-14 font-medium mb-1">Perfil: {profile.name}</div>
            <p className="text-12 text-ink-4 max-w-lg">
              Se evaluará el encaje de esta licitación con tu perfil de empresa.
              {profile.certifications.length > 0 && (
                <> Certificaciones: {profile.certifications.join(', ')}.</>
              )}
            </p>
          </div>
          <button onClick={handleCalculate} className="btn primary">
            Calcular match score
          </button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex flex-col gap-4">
          <div className="t-up">Analizando encaje licitación-empresa…</div>
          <div className="flex flex-col gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-4 bg-surface-2 rounded animate-pulse" style={{ width: `${50 + i * 10}%` }} />
            ))}
          </div>
          <p className="text-12 text-ink-4">
            Se extraen los requisitos del pliego y se comparan con tu perfil de empresa.
          </p>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="text-12 text-red-500 bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
          {error}
        </div>
      )}

      {/* Results */}
      {!loading && result && (
        <div className="flex flex-col gap-5">
          {/* Score header */}
          <div className="surface p-5 flex items-center gap-6">
            <div className="flex flex-col items-center">
              <div className="text-3xl font-bold tabular-nums">{result.puntuacion_total}</div>
              <div className="t-xs t-mute">/ 100</div>
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-12 px-2 py-0.5 rounded border ${nivelColor(result.nivel_encaje)}`}>
                  {result.nivel_encaje}
                </span>
                {result.cached && (
                  <span className="text-11 text-ink-4">(resultado cacheado)</span>
                )}
              </div>
              <div className="text-13 leading-relaxed">{result.resumen}</div>
            </div>
          </div>

          {/* Score bar */}
          <div className="h-2 bg-surface-2 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                result.puntuacion_total >= 70 ? 'bg-green-500' :
                result.puntuacion_total >= 40 ? 'bg-yellow-500' : 'bg-red-400'
              }`}
              style={{ width: `${result.puntuacion_total}%` }}
            />
          </div>

          {/* Breakdown by criterion */}
          {result.desglose.length > 0 && (
            <div>
              <div className="t-up mb-3">Desglose por criterio</div>
              <div className="flex flex-col gap-3">
                {result.desglose.map((d, i) => (
                  <div key={i} className="surface p-4">
                    <div className="flex justify-between items-center mb-2">
                      <span className="t-medium text-13">{d.criterio}</span>
                      <span className={`text-14 font-semibold tabular-nums ${scoreColor(d.puntuacion)}`}>
                        {d.puntuacion}/10
                      </span>
                    </div>
                    <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden mb-2">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ${
                          d.puntuacion >= 7 ? 'bg-green-500' :
                          d.puntuacion >= 4 ? 'bg-yellow-500' : 'bg-red-400'
                        }`}
                        style={{ width: `${d.puntuacion * 10}%` }}
                      />
                    </div>
                    <div className="text-12 text-ink-3 leading-relaxed">{d.justificacion}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Requirements matching */}
          {result.requisitos_evaluados.length > 0 && (
            <RequirementsMatchSection requisitos={result.requisitos_evaluados} onOpenDocument={onOpenDocument} />
          )}

          {/* Recalculate button */}
          <div className="flex justify-end">
            <button onClick={handleCalculate} className="btn secondary text-12" disabled={loading}>
              Recalcular
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function RequirementsMatchSection({ requisitos, onOpenDocument }: { requisitos: RequirementMatch[]; onOpenDocument: (opts: { filename?: string; documentType?: string; page?: number | null }) => void }) {
  const { cumplidos, no_cumplidos, indeterminados } = groupReqsByEstado(requisitos);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const DOC_TYPE_LABELS: Record<string, string> = { pcap: 'PCAP', ppt: 'PPT', anexo: 'Anexo' };

  return (
    <div>
      <div className="t-up mb-3">Requisitos evaluados</div>
      <div className="flex gap-3 mb-4 text-12">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-green-500" />
          {cumplidos.length} cumplidos
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-red-400" />
          {no_cumplidos.length} no cumplidos
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-yellow-400" />
          {indeterminados.length} indeterminados
        </span>
      </div>

      <div className="flex flex-col gap-2">
        {requisitos.map((req) => {
          const config = ESTADO_CONFIG[req.estado] || ESTADO_CONFIG.indeterminado;
          const isExpanded = expandedId === req.requisito_id;

          return (
            <div key={req.requisito_id} className={`rounded border overflow-hidden ${config.bg}`}>
              <button
                type="button"
                className="w-full p-3 flex items-start gap-2 text-left hover:opacity-80 transition-opacity"
                onClick={() => setExpandedId(isExpanded ? null : req.requisito_id)}
              >
                <span className={`shrink-0 mt-1.5 w-2 h-2 rounded-full ${config.dot}`} />
                <div className="flex-1 min-w-0">
                  <div className="text-13 leading-relaxed">{req.descripcion}</div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={`text-11 font-medium ${config.text}`}>{config.label}</span>
                    <span className="text-11 text-ink-4">— {req.categoria}</span>
                  </div>
                </div>
                <span className={`shrink-0 text-ink-4 text-11 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                  ▸
                </span>
              </button>

              {isExpanded && (
                <div className="px-3 pb-3 pt-0 border-t border-line/30">
                  <div className="flex flex-col gap-2 mt-3">
                    <div className="text-12 text-ink-3 leading-relaxed">
                      <span className="font-medium text-ink-2">Justificación:</span> {req.justificacion}
                    </div>
                    {req.documento_origen && (
                      <div className="text-12 text-ink-4">
                        Fuente: {DOC_TYPE_LABELS[req.documento_origen] || req.documento_origen}
                        {req.pagina != null && `, página ${req.pagina}`}
                      </div>
                    )}
                    {req.pagina != null && req.documento_origen && (
                      <button
                        className="self-start text-12 text-accent hover:underline flex items-center gap-1"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenDocument({
                            documentType: req.documento_origen!,
                            page: req.pagina,
                          });
                        }}
                      >
                        Abrir documento en p. {req.pagina} ↗
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
