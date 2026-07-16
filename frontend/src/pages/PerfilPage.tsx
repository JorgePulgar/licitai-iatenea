import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { Button } from "../components/ui/Button";
import { Input, Textarea } from "../components/ui/Input";
import { SkeletonRows } from "../components/ui/Skeleton";
import { ApiError } from "../lib/http";
import { getProfile, saveProfile } from "../services/perfil";
import type { CompanyProfileInput } from "../types/api";

const EMPTY: CompanyProfileInput = {
  name: "",
  description: null,
  sectors: [],
  certifications: [],
  employee_count: null,
  annual_revenue: null,
  notable_clients: [],
  solvency_tech: null,
  solvency_econ: null,
};

/**
 * Perfil de empresa mínimo (DM6): única fuente de capacidades para el match y
 * la memoria. Los campos-lista se editan separados por comas.
 */
export function PerfilPage() {
  const [form, setForm] = useState<CompanyProfileInput>(EMPTY);
  const [saved, setSaved] = useState(false);
  const queryClient = useQueryClient();

  const { data, isPending, error } = useQuery({
    queryKey: ["perfil"],
    queryFn: getProfile,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });

  useEffect(() => {
    if (data) {
      setForm({
        name: data.name,
        description: data.description,
        sectors: data.sectors,
        certifications: data.certifications,
        employee_count: data.employee_count,
        annual_revenue: data.annual_revenue,
        notable_clients: data.notable_clients,
        solvency_tech: data.solvency_tech,
        solvency_econ: data.solvency_econ,
      });
    }
  }, [data]);

  const mutation = useMutation({
    mutationFn: saveProfile,
    onSuccess: () => {
      setSaved(true);
      queryClient.invalidateQueries({ queryKey: ["perfil"] });
    },
  });

  const notFound = error instanceof ApiError && error.status === 404;
  if (isPending && !notFound) return <SkeletonRows rows={6} />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    mutation.mutate(form);
  };

  const set = <K extends keyof CompanyProfileInput>(key: K, value: CompanyProfileInput[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const listValue = (values: string[]) => values.join(", ");
  const parseList = (raw: string) =>
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-ink-1">Perfil de empresa</h1>
        <p className="mt-1 text-sm text-ink-2">
          El match score y la memoria técnica solo afirman lo que consta aquí: cuanto más
          completo, menos huecos [COMPLETAR: …] en los borradores.
        </p>
      </div>

      <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
        <div className="md:col-span-2">
          <Input
            label="Nombre de la empresa"
            required
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </div>
        <div className="md:col-span-2">
          <Textarea
            label="Descripción"
            rows={3}
            value={form.description ?? ""}
            onChange={(e) => set("description", e.target.value || null)}
          />
        </div>
        <Input
          label="Sectores"
          help="Separados por comas"
          value={listValue(form.sectors)}
          onChange={(e) => set("sectors", parseList(e.target.value))}
        />
        <Input
          label="Certificaciones"
          help="Separadas por comas (ISO 9001, ENS…)"
          value={listValue(form.certifications)}
          onChange={(e) => set("certifications", parseList(e.target.value))}
        />
        <Input
          label="Nº de empleados"
          type="number"
          min={0}
          value={form.employee_count ?? ""}
          onChange={(e) =>
            set("employee_count", e.target.value ? Number(e.target.value) : null)
          }
        />
        <Input
          label="Facturación anual"
          value={form.annual_revenue ?? ""}
          onChange={(e) => set("annual_revenue", e.target.value || null)}
        />
        <div className="md:col-span-2">
          <Input
            label="Clientes destacados"
            help="Separados por comas"
            value={listValue(form.notable_clients)}
            onChange={(e) => set("notable_clients", parseList(e.target.value))}
          />
        </div>
        <Textarea
          label="Solvencia técnica"
          rows={3}
          value={form.solvency_tech ?? ""}
          onChange={(e) => set("solvency_tech", e.target.value || null)}
        />
        <Textarea
          label="Solvencia económica"
          rows={3}
          value={form.solvency_econ ?? ""}
          onChange={(e) => set("solvency_econ", e.target.value || null)}
        />
        <div className="flex items-center gap-3 md:col-span-2">
          <Button type="submit" loading={mutation.isPending}>
            Guardar perfil
          </Button>
          {saved && <span className="text-sm text-ok">Perfil guardado.</span>}
          {mutation.isError && (
            <span className="text-sm text-danger">No se pudo guardar.</span>
          )}
        </div>
      </form>
    </div>
  );
}
