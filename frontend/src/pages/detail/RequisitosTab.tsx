import { useQuery } from "@tanstack/react-query";
import { Badge } from "../../components/ui/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import { SkeletonRows } from "../../components/ui/Skeleton";
import { getRequirements } from "../../services/licitaciones";
import type { Requirement } from "../../types/api";

const CATEGORY_LABELS: Record<Requirement["categoria"], string> = {
  administrativo: "Administrativo",
  tecnico: "Técnico",
  economico: "Económico",
  plazo: "Plazo",
};

const CATEGORY_ORDER: Requirement["categoria"][] = [
  "administrativo",
  "tecnico",
  "economico",
  "plazo",
];

/** Checklist de requisitos con referencia de página (spec-demo-minimal §3.4). */
export function RequisitosTab({ licitacionId }: { licitacionId: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["requirements", licitacionId],
    queryFn: () => getRequirements(licitacionId),
    staleTime: Infinity, // el backend cachea; regenerar es acción explícita
  });

  if (isPending)
    return (
      <div className="space-y-2">
        <p className="text-sm text-ink-3">
          Extrayendo requisitos del pliego… (la primera vez tarda un poco)
        </p>
        <SkeletonRows rows={6} />
      </div>
    );
  if (isError)
    return <p className="text-sm text-danger">No se pudieron extraer los requisitos.</p>;
  if (!data || data.requirements.length === 0)
    return (
      <EmptyState
        title="Sin requisitos extraídos"
        hint="El pliego no contiene requisitos reconocibles o aún no está indexado."
      />
    );

  return (
    <div className="space-y-5">
      {CATEGORY_ORDER.map((categoria) => {
        const items = data.requirements.filter((r) => r.categoria === categoria);
        if (items.length === 0) return null;
        return (
          <section key={categoria}>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-3">
              {CATEGORY_LABELS[categoria]} ({items.length})
            </h2>
            <ul className="divide-y divide-line rounded-md border border-line bg-surface">
              {items.map((req) => (
                <li key={req.id} className="flex items-start gap-3 px-4 py-2.5 text-sm">
                  <span className="mt-0.5">
                    {req.es_obligatorio ? (
                      <Badge tone="danger">obligatorio</Badge>
                    ) : (
                      <Badge>valorable</Badge>
                    )}
                  </span>
                  <span className="flex-1 text-ink-1">{req.descripcion}</span>
                  {req.pagina && (
                    <span className="shrink-0 font-mono text-xs text-accent">
                      [{req.documento_origen} p. {req.pagina}]
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
