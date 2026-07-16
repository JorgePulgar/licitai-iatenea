import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useState } from "react";
import { Markdown } from "../../components/Markdown";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import {
  generatePropuesta,
  listDocuments,
  proposeEsquema,
  refineViaChat,
} from "../../services/memoria";
import type { MemoriaSectionDraft } from "../../types/api";

/**
 * Vista de Memoria (spec-demo-minimal §3.5): esquema → generar → chat-refine →
 * Markdown renderizado. Sin editor TipTap, sin export, sin paginación.
 */
export function MemoriaTab({ licitacionId }: { licitacionId: string }) {
  const [esquema, setEsquema] = useState<MemoriaSectionDraft[] | null>(null);
  const [esquemaReply, setEsquemaReply] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const docsKey = ["memoria-docs", licitacionId];
  const { data: documents = [] } = useQuery({
    queryKey: docsKey,
    queryFn: () => listDocuments(licitacionId),
  });
  const currentDoc = documents[0] ?? null;

  const esquemaMutation = useMutation({
    mutationFn: () => proposeEsquema(licitacionId),
    onSuccess: (data) => {
      setEsquema(data.esquema);
      setEsquemaReply(data.reply);
    },
  });

  const propuestaMutation = useMutation({
    mutationFn: (sections: MemoriaSectionDraft[]) =>
      generatePropuesta(licitacionId, sections),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: docsKey }),
  });

  // Sin documento aún: flujo esquema → generar.
  if (!currentDoc) {
    return (
      <div className="space-y-4">
        {!esquema && (
          <EmptyState
            title="Todavía no hay borrador de memoria"
            hint="Primero se extrae del pliego la estructura exigida; después se redacta cada apartado con las capacidades reales de tu empresa."
            action={
              <Button
                onClick={() => esquemaMutation.mutate()}
                loading={esquemaMutation.isPending}
              >
                Extraer estructura del pliego
              </Button>
            }
          />
        )}
        {esquemaMutation.isError && (
          <p className="text-sm text-danger">No se pudo extraer la estructura.</p>
        )}
        {esquema && (
          <>
            {esquemaReply && <p className="text-sm text-ink-2">{esquemaReply}</p>}
            {esquema.length === 0 ? (
              <EmptyState title="El pliego no aporta estructura ni criterios suficientes" />
            ) : (
              <>
                <ol className="divide-y divide-line rounded-md border border-line bg-surface">
                  {esquema.map((section) => (
                    <li key={section.sort_order} className="px-4 py-2.5 text-sm">
                      <span className="font-medium text-ink-1">{section.title}</span>
                      {section.criterio_adjudicacion && (
                        <span className="ml-2 text-ink-3">
                          — {section.criterio_adjudicacion}
                          {section.max_puntos != null && ` (${section.max_puntos} pts)`}
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
                <Button
                  onClick={() => propuestaMutation.mutate(esquema)}
                  loading={propuestaMutation.isPending}
                >
                  {propuestaMutation.isPending
                    ? "Redactando apartados…"
                    : "Redactar borrador"}
                </Button>
                {propuestaMutation.isError && (
                  <p className="text-sm text-danger">La redacción falló. Reintenta.</p>
                )}
              </>
            )}
          </>
        )}
      </div>
    );
  }

  return <DraftView licitacionId={licitacionId} docId={currentDoc.id} />;
}

/** Borrador renderizado + chat de refinado en vivo (fast path de la demo, R2). */
function DraftView({ licitacionId, docId }: { licitacionId: string; docId: string }) {
  const [message, setMessage] = useState("");
  const [lastReply, setLastReply] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: documents = [] } = useQuery({
    queryKey: ["memoria-docs", licitacionId],
    queryFn: () => listDocuments(licitacionId),
  });
  const doc = documents.find((d) => d.id === docId) ?? documents[0];
  const markdown = doc?.markdown ?? "";

  const refineMutation = useMutation({
    mutationFn: (instruction: string) =>
      refineViaChat(licitacionId, { doc_id: docId, markdown, message: instruction }),
    onSuccess: (data) => {
      setLastReply(data.texto_chat);
      setMessage("");
      queryClient.invalidateQueries({ queryKey: ["memoria-docs", licitacionId] });
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = message.trim();
    if (trimmed) refineMutation.mutate(trimmed);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <Card className="max-h-[70vh] overflow-y-auto p-6">
        <Markdown>{markdown}</Markdown>
      </Card>

      <div className="space-y-3">
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-ink-1">Refinar con IA</h3>
          <p className="mb-3 text-xs text-ink-3">
            Pide un cambio concreto; el resto del documento se conserva tal cual. Los
            huecos <mark className="gap-marker">[COMPLETAR: …]</mark> marcan datos de tu
            empresa que faltan — rellénalos, no los inventa.
          </p>
          <form onSubmit={submit} className="space-y-2">
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={3}
              placeholder='Ej.: "Acorta la introducción del apartado 2"'
              aria-label="Instrucción de refinado"
              className="w-full rounded border border-line bg-surface px-3 py-2 text-sm placeholder:text-ink-3 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <Button type="submit" loading={refineMutation.isPending} className="w-full">
              Aplicar cambio
            </Button>
          </form>
          {refineMutation.isError && (
            <p className="mt-2 text-sm text-danger">El cambio no se pudo aplicar.</p>
          )}
          {lastReply && !refineMutation.isPending && (
            <p className="mt-2 rounded bg-bg p-2 text-xs text-ink-2">{lastReply}</p>
          )}
        </Card>
      </div>
    </div>
  );
}
