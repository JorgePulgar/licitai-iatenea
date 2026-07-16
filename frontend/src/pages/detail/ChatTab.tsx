import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { Markdown } from "../../components/Markdown";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { askQuestion, getHistory } from "../../services/query";
import type { Citation } from "../../types/api";

function newSessionId(): string {
  return crypto.randomUUID();
}

/** Chat RAG con citas [p. X] clicables que muestran el fragmento fuente. */
export function ChatTab({ licitacionId }: { licitacionId: string }) {
  const [sessionId] = useState(newSessionId);
  const [question, setQuestion] = useState("");
  const [openCitations, setOpenCitations] = useState<Citation[] | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const historyKey = ["query-history", licitacionId, sessionId];
  const { data: turns = [] } = useQuery({
    queryKey: historyKey,
    queryFn: () => getHistory(licitacionId, sessionId),
  });

  const mutation = useMutation({
    mutationFn: (q: string) =>
      askQuestion({ question: q, licitacion_id: licitacionId, session_id: sessionId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: historyKey });
      setQuestion("");
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, mutation.isPending]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (trimmed) mutation.mutate(trimmed);
  };

  return (
    <div className="flex h-[65vh] flex-col rounded-md border border-line bg-surface">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {turns.length === 0 && !mutation.isPending && (
          <EmptyState
            title="Pregunta lo que necesites sobre este pliego"
            hint='Ej.: "¿Cuál es el presupuesto base de licitación?" — cada respuesta cita la página de origen.'
          />
        )}
        {turns.map((turn) => (
          <div key={turn.id} className="space-y-2">
            <div className="ml-auto w-fit max-w-[85%] rounded-md bg-accent/10 px-3 py-2 text-sm text-ink-1">
              {turn.question}
            </div>
            <div className="w-fit max-w-[85%] rounded-md border border-line px-3 py-2">
              <Markdown onCitationClick={() => setOpenCitations(turn.citations)}>
                {turn.answer}
              </Markdown>
              {turn.citations.length > 0 && (
                <button
                  type="button"
                  onClick={() => setOpenCitations(turn.citations)}
                  className="mt-2 text-xs font-medium text-accent hover:underline"
                >
                  Ver {turn.citations.length} fragmento(s) citado(s)
                </button>
              )}
            </div>
          </div>
        ))}
        {mutation.isPending && (
          <div className="w-fit rounded-md border border-line px-3 py-2 text-sm text-ink-3">
            Buscando en el pliego…
          </div>
        )}
        {mutation.isError && (
          <p className="text-sm text-danger">La consulta falló. Vuelve a intentarlo.</p>
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={submit} className="flex gap-2 border-t border-line p-3">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Escribe tu pregunta sobre el pliego…"
          aria-label="Pregunta sobre el pliego"
          className="flex-1 rounded border border-line bg-surface px-3 py-2 text-sm placeholder:text-ink-3 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <Button type="submit" loading={mutation.isPending}>
          Enviar
        </Button>
      </form>

      {openCitations && (
        <CitationsPanel citations={openCitations} onClose={() => setOpenCitations(null)} />
      )}
    </div>
  );
}

/** Los fragmentos fuente de una respuesta (contexto de página de cada cita). */
function CitationsPanel({
  citations,
  onClose,
}: {
  citations: Citation[];
  onClose: () => void;
}) {
  return (
    <div className="border-t border-line bg-bg p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-1">Fragmentos citados</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-ink-3 hover:text-ink-1"
        >
          Cerrar
        </button>
      </div>
      <div className="max-h-48 space-y-2 overflow-y-auto">
        {citations.map((citation, i) => (
          <blockquote
            key={i}
            className="rounded border border-line bg-surface p-2 text-xs text-ink-2"
          >
            <span className="mb-1 block font-mono text-accent">
              [{citation.document_type} p. {citation.page_number ?? "?"}] — {citation.filename}
            </span>
            {citation.content}
          </blockquote>
        ))}
      </div>
    </div>
  );
}
