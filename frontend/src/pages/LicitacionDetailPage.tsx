import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { SkeletonRows } from "../components/ui/Skeleton";
import { Tabs } from "../components/ui/Tabs";
import { getLicitacion } from "../services/licitaciones";
import { ChatTab } from "./detail/ChatTab";
import { MatchTab } from "./detail/MatchTab";
import { MemoriaTab } from "./detail/MemoriaTab";
import { RequisitosTab } from "./detail/RequisitosTab";

const TABS = [
  { id: "requisitos", label: "Requisitos" },
  { id: "chat", label: "Consultas" },
  { id: "match", label: "Match" },
  { id: "memoria", label: "Memoria" },
];

/** Vista de procesamiento + detalle con pestañas (spec-demo-minimal §3.3-3.5). */
export function LicitacionDetailPage() {
  const { id = "", tab = "requisitos" } = useParams();
  const navigate = useNavigate();

  const { data: licitacion, isPending } = useQuery({
    queryKey: ["licitacion", id],
    queryFn: () => getLicitacion(id),
    // Mientras el pipeline procesa, se repregunta cada 4 s (vista de procesamiento).
    refetchInterval: (query) =>
      query.state.data?.status === "processing" ? 4000 : false,
  });

  if (isPending) return <SkeletonRows rows={5} />;
  if (!licitacion) return <p className="text-sm text-danger">Licitación no encontrada.</p>;

  const processing = licitacion.status === "processing";

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-ink-1">{licitacion.title}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-2">
          {licitacion.documents.map((doc) => (
            <span key={doc.id} className="inline-flex items-center gap-1">
              <span className="font-mono text-xs uppercase text-ink-3">
                {doc.document_type}
              </span>
              {doc.status === "indexed" && <Badge tone="ok">indexado</Badge>}
              {doc.status === "processing" && <Badge tone="accent">procesando</Badge>}
              {doc.status === "uploaded" && <Badge>en cola</Badge>}
              {doc.status === "error" && <Badge tone="danger">error</Badge>}
            </span>
          ))}
          {licitacion.deadline && <span>· Límite: {licitacion.deadline}</span>}
        </div>
      </div>

      {processing ? (
        <div className="rounded-md border border-line bg-surface p-8 text-center">
          <div className="mx-auto mb-3 h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="text-sm font-medium text-ink-1">Procesando los pliegos…</p>
          <p className="mt-1 text-sm text-ink-3">
            OCR, troceado e indexación. Esta vista se actualiza sola.
          </p>
        </div>
      ) : (
        <>
          <Tabs
            tabs={TABS}
            active={tab}
            onChange={(next) => navigate(`/licitaciones/${id}/${next}`)}
          />
          {tab === "requisitos" && <RequisitosTab licitacionId={id} />}
          {tab === "chat" && <ChatTab licitacionId={id} />}
          {tab === "match" && <MatchTab licitacionId={id} />}
          {tab === "memoria" && <MemoriaTab licitacionId={id} />}
        </>
      )}
    </div>
  );
}
