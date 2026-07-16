import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { SkeletonRows } from "../components/ui/Skeleton";
import { ApiError } from "../lib/http";
import { createLicitacion, listLicitaciones } from "../services/licitaciones";
import type { Licitacion } from "../types/api";

const ESTADO_LABELS: Record<Licitacion["estado"], string> = {
  elaborando: "Elaborando",
  revision_comercial: "Revisión comercial",
  entregada: "Entregada",
  resuelta: "Resuelta",
};

function PipelineBadge({ status }: { status: Licitacion["status"] }) {
  if (status === "indexed") return <Badge tone="ok">Indexada</Badge>;
  if (status === "processing") return <Badge tone="accent">Procesando…</Badge>;
  if (status === "partial_error") return <Badge tone="warn">Parcial</Badge>;
  return <Badge tone="danger">Error</Badge>;
}

export function LicitacionesPage() {
  const [createOpen, setCreateOpen] = useState(false);
  const { data, isPending, isError } = useQuery({
    queryKey: ["licitaciones"],
    queryFn: listLicitaciones,
  });

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-ink-1">Licitaciones</h1>
        <Button onClick={() => setCreateOpen(true)}>Nueva licitación</Button>
      </div>

      {isPending && <SkeletonRows rows={4} />}
      {isError && (
        <p className="text-sm text-danger">
          No se pudieron cargar las licitaciones. Recarga la página.
        </p>
      )}
      {data && data.length === 0 && (
        <EmptyState
          title="Aún no hay licitaciones"
          hint="Sube el PCAP (y opcionalmente el PPT) de una licitación para analizarla."
          action={<Button onClick={() => setCreateOpen(true)}>Subir pliego</Button>}
        />
      )}
      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-line bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-3">
                <th className="px-4 py-2 font-medium">Título</th>
                <th className="px-4 py-2 font-medium">Documentos</th>
                <th className="px-4 py-2 font-medium">Pipeline</th>
                <th className="px-4 py-2 font-medium">Estado</th>
                <th className="px-4 py-2 font-medium">Límite</th>
              </tr>
            </thead>
            <tbody>
              {data.map((lic) => (
                <tr key={lic.id} className="border-b border-line last:border-0 hover:bg-bg">
                  <td className="px-4 py-2.5">
                    <Link
                      to={`/licitaciones/${lic.id}/requisitos`}
                      className="font-medium text-ink-1 hover:text-accent"
                    >
                      {lic.title}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-ink-2">
                    {lic.documents.map((d) => d.document_type).join(", ") || "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <PipelineBadge status={lic.status} />
                  </td>
                  <td className="px-4 py-2.5 text-ink-2">{ESTADO_LABELS[lic.estado]}</td>
                  <td className="px-4 py-2.5 text-ink-2">{lic.deadline ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

function CreateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [pcap, setPcap] = useState<File | null>(null);
  const [ppt, setPpt] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: createLicitacion,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["licitaciones"] });
      setTitle("");
      setPcap(null);
      setPpt(null);
      setError(null);
      onClose();
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Error subiendo los pliegos.");
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!pcap) {
      setError("El PCAP es obligatorio.");
      return;
    }
    mutation.mutate({ title, pcap, ppt: ppt ?? undefined });
  };

  return (
    <Modal open={open} title="Nueva licitación" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Input
          label="Título"
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Servicio de mantenimiento de..."
        />
        <Input
          label="PCAP (PDF)"
          type="file"
          accept="application/pdf"
          required
          onChange={(e) => setPcap(e.target.files?.[0] ?? null)}
        />
        <Input
          label="PPT (PDF, opcional)"
          type="file"
          accept="application/pdf"
          onChange={(e) => setPpt(e.target.files?.[0] ?? null)}
        />
        {error && <p className="text-sm text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            Subir y procesar
          </Button>
        </div>
      </form>
    </Modal>
  );
}
