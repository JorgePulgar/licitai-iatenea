import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import type { Licitacion } from "../types/api";

export const FIXTURE_LICITACION: Licitacion = {
  id: "lic-1",
  title: "Servicio de mantenimiento de aplicaciones",
  status: "indexed",
  estado: "elaborando",
  resultado: null,
  deadline: "2026-09-01",
  created_at: "2026-07-01T10:00:00Z",
  updated_at: "2026-07-01T10:05:00Z",
  documents: [
    {
      id: "pliego-1",
      licitacion_id: "lic-1",
      document_type: "PCAP",
      filename: "pcap.pdf",
      doc_title: null,
      size_bytes: 1000,
      uploaded_at: "2026-07-01T10:00:00Z",
      processed_at: "2026-07-01T10:05:00Z",
      status: "indexed",
      low_quality_flag: false,
    },
  ],
};

export const handlers = [
  http.post("/api/v1/auth/login", () =>
    HttpResponse.json({ access_token: "token-123", token_type: "bearer" }),
  ),
  http.get("/api/v1/licitaciones/", () => HttpResponse.json([FIXTURE_LICITACION])),
  http.get("/api/v1/licitaciones/lic-1", () => HttpResponse.json(FIXTURE_LICITACION)),
  http.get("/api/v1/licitaciones/lic-1/requirements", () =>
    HttpResponse.json({
      licitacion_id: "lic-1",
      requirements: [
        {
          id: "req-1",
          categoria: "tecnico",
          descripcion: "Equipo mínimo de 3 desarrolladores senior",
          pagina: 14,
          documento_origen: "ppt",
          es_obligatorio: true,
        },
      ],
      cached: true,
      generated_at: "2026-07-01T10:10:00Z",
    }),
  ),
  http.get("/api/v1/query/lic-1/history", () => HttpResponse.json([])),
  http.get("/api/v1/licitaciones/lic-1/memoria/documents", () =>
    HttpResponse.json([
      {
        id: "doc-1",
        licitacion_id: "lic-1",
        title: "Borrador de Memoria",
        markdown:
          "# Memoria\n\n## Plan de trabajo\n\nTexto con hueco [COMPLETAR: certificaciones de calidad].",
        updated_at: "2026-07-01T11:00:00Z",
      },
    ]),
  ),
  http.get("/api/v1/perfil/", () =>
    HttpResponse.json({
      id: "prof-1",
      name: "Iatenea SL",
      description: null,
      sectors: ["TIC"],
      certifications: [],
      employee_count: 12,
      annual_revenue: null,
      notable_clients: [],
      solvency_tech: null,
      solvency_econ: null,
      is_default: true,
      updated_at: "2026-07-01T09:00:00Z",
    }),
  ),
];

export const server = setupServer(...handlers);
