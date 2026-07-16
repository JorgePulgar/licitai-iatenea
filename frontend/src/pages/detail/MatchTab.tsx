import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { ApiError } from "../../lib/http";
import { computeMatch } from "../../services/licitaciones";

const NIVEL_COLORS: Record<string, string> = {
  Alto: "text-ok",
  Medio: "text-warn",
  Bajo: "text-danger",
};

/** Puntuación de encaje pliego↔empresa con justificación (demo §1). */
export function MatchTab({ licitacionId }: { licitacionId: string }) {
  const mutation = useMutation({ mutationFn: () => computeMatch(licitacionId) });
  const result = mutation.data;

  if (!result) {
    const needsProfile =
      mutation.error instanceof ApiError && mutation.error.status === 400;
    return (
      <EmptyState
        title="Match score pliego ↔ empresa"
        hint={
          needsProfile
            ? "Configura primero el perfil de empresa para calcular el encaje."
            : "Evalúa el encaje de tu empresa con los requisitos de este pliego."
        }
        action={
          needsProfile ? (
            <Link to="/perfil" className="text-sm font-medium text-accent hover:underline">
              Ir al perfil de empresa
            </Link>
          ) : (
            <Button onClick={() => mutation.mutate()} loading={mutation.isPending}>
              Calcular match
            </Button>
          )
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <Card className="flex items-center gap-6 p-5">
        <div>
          <div className="text-4xl font-semibold text-ink-1">
            {result.puntuacion_total}
            <span className="text-lg text-ink-3">/100</span>
          </div>
          <div className={`text-sm font-medium ${NIVEL_COLORS[result.nivel_encaje] ?? ""}`}>
            Encaje {result.nivel_encaje}
          </div>
        </div>
        <p className="flex-1 text-sm text-ink-2">{result.resumen}</p>
      </Card>

      <div className="space-y-2">
        {result.desglose.map((criterion, i) => (
          <Card key={i} className="p-4">
            <div className="flex items-center justify-between gap-4">
              <span className="text-sm font-medium text-ink-1">{criterion.criterio}</span>
              <span className="font-mono text-sm text-ink-1">{criterion.puntuacion}/10</span>
            </div>
            <div className="mt-1.5 h-1.5 w-full rounded bg-line">
              <div
                className="h-1.5 rounded bg-accent"
                style={{ width: `${criterion.puntuacion * 10}%` }}
              />
            </div>
            <p className="mt-2 text-sm text-ink-2">{criterion.justificacion}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
