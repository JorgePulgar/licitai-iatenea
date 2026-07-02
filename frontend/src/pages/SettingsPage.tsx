import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import AppShell from '../components/layout/AppShell';
import {
  fetchCompanyProfile,
  updateCompanyProfile,
  fetchCompanyTemplates,
  uploadCompanyTemplate,
  deleteCompanyTemplate,
} from '../services/api';
import type {
  CompanyProfileUpdate,
  CompanyTemplateResponse,
} from '../types/licitacion';

const EMPTY_FORM: CompanyProfileUpdate = {
  name: '',
  description: '',
  sectors: [],
  certifications: [],
  employee_count: undefined,
  annual_revenue: '',
  notable_clients: [],
  solvency_tech: '',
  solvency_econ: '',
};

export default function SettingsPage() {
  const [form, setForm] = useState<CompanyProfileUpdate>({ ...EMPTY_FORM });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);

  useEffect(() => {
    fetchCompanyProfile()
      .then((profile) => {
        setForm({
          name: profile.name,
          description: profile.description || '',
          sectors: profile.sectors,
          certifications: profile.certifications,
          employee_count: profile.employee_count ?? undefined,
          annual_revenue: profile.annual_revenue || '',
          notable_clients: profile.notable_clients,
          solvency_tech: profile.solvency_tech || '',
          solvency_econ: profile.solvency_econ || '',
        });
      })
      .catch(() => {
        setIsNew(true);
      })
      .finally(() => setLoading(false));
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;

    setSaving(true);
    setError(null);
    setSaved(false);

    try {
      await updateCompanyProfile(form);
      setSaved(true);
      setIsNew(false);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al guardar el perfil');
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell crumbs={['Ajustes']}>
      <div className="page">
        <div className="t-up mb-1">Perfil de empresa</div>
        <p className="text-12 text-ink-4 mb-6">
          Estos datos se utilizan para calcular el match score y evaluar requisitos de cada licitación.
          {isNew && ' Configura tu perfil para empezar.'}
        </p>

        {loading ? (
          <div className="flex flex-col gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-10 bg-surface-2 rounded animate-pulse" />
            ))}
          </div>
        ) : (
          <form onSubmit={handleSave} className="flex flex-col gap-5">
            {/* Datos generales */}
            <fieldset className="flex flex-col gap-3">
              <legend className="text-13 font-medium text-ink-2 mb-2">Datos generales</legend>

              <div>
                <label className="label">Nombre de la empresa *</label>
                <input
                  className="real-input w-full"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Mi Empresa Consultoría S.L."
                />
              </div>

              <div>
                <label className="label">Descripción</label>
                <textarea
                  className="real-input w-full min-h-[80px] resize-y"
                  value={form.description || ''}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="Empresa de consultoría tecnológica especializada en transformación digital..."
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Facturación anual</label>
                  <input
                    className="real-input w-full"
                    value={form.annual_revenue || ''}
                    onChange={(e) => setForm({ ...form, annual_revenue: e.target.value })}
                    placeholder="5-10 millones €"
                  />
                </div>
                <div>
                  <label className="label">Número de empleados</label>
                  <input
                    className="real-input w-full"
                    type="number"
                    min={1}
                    value={form.employee_count ?? ''}
                    onChange={(e) => setForm({
                      ...form,
                      employee_count: e.target.value ? parseInt(e.target.value, 10) : undefined,
                    })}
                    placeholder="80"
                  />
                </div>
              </div>
            </fieldset>

            {/* Certificaciones */}
            <fieldset className="flex flex-col gap-3">
              <legend className="text-13 font-medium text-ink-2 mb-2">Certificaciones</legend>
              <TagInput
                tags={form.certifications || []}
                onChange={(tags) => setForm({ ...form, certifications: tags })}
                placeholder="Escribe y pulsa Enter (ej: ISO 9001, ISO 27001, ENS nivel medio)"
              />
            </fieldset>

            {/* Solvencia */}
            <fieldset className="flex flex-col gap-3">
              <legend className="text-13 font-medium text-ink-2 mb-2">Solvencia</legend>

              <div>
                <label className="label">Solvencia técnica</label>
                <textarea
                  className="real-input w-full min-h-[80px] resize-y"
                  value={form.solvency_tech || ''}
                  onChange={(e) => setForm({ ...form, solvency_tech: e.target.value })}
                  placeholder="Experiencia en proyectos similares, equipo técnico, medios materiales..."
                />
              </div>

              <div>
                <label className="label">Solvencia económica</label>
                <textarea
                  className="real-input w-full min-h-[60px] resize-y"
                  value={form.solvency_econ || ''}
                  onChange={(e) => setForm({ ...form, solvency_econ: e.target.value })}
                  placeholder="Cifra de negocio mínima, seguros de responsabilidad civil..."
                />
              </div>
            </fieldset>

            {/* Sectores */}
            <fieldset className="flex flex-col gap-3">
              <legend className="text-13 font-medium text-ink-2 mb-2">Sectores</legend>
              <TagInput
                tags={form.sectors || []}
                onChange={(tags) => setForm({ ...form, sectors: tags })}
                placeholder="Escribe y pulsa Enter (ej: TIC, Consultoría, Sanidad)"
              />
            </fieldset>

            {/* Clientes */}
            <fieldset className="flex flex-col gap-3">
              <legend className="text-13 font-medium text-ink-2 mb-2">Clientes destacados</legend>
              <TagInput
                tags={form.notable_clients || []}
                onChange={(tags) => setForm({ ...form, notable_clients: tags })}
                placeholder="Escribe y pulsa Enter (ej: Ministerio de Defensa, AENA)"
              />
            </fieldset>

            {/* Actions */}
            {error && (
              <div className="text-12 text-red-500 bg-red-50 border border-red-200 rounded px-3 py-2">
                {error}
              </div>
            )}

            {saved && (
              <div className="text-12 text-green-700 bg-green-50 border border-green-200 rounded px-3 py-2">
                Perfil guardado correctamente
              </div>
            )}

            <div className="flex justify-end">
              <button
                type="submit"
                className="btn primary"
                disabled={saving || !form.name.trim()}
              >
                {saving ? 'Guardando…' : isNew ? 'Crear perfil' : 'Guardar cambios'}
              </button>
            </div>
          </form>
        )}

        <hr className="my-8 border-ink-6" />

        <CompanyTemplatesSection />
      </div>
    </AppShell>
  );
}


// ── Plantillas de referencia (CompanyTemplate) ──

function CompanyTemplatesSection() {
  const [templates, setTemplates] = useState<CompanyTemplateResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchCompanyTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  async function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      const created = await uploadCompanyTemplate(file, { title: file.name });
      setTemplates((prev) => [created, ...(prev || [])]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al subir el documento');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  async function onDelete(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await deleteCompanyTemplate(id);
      setTemplates((prev) => (prev || []).filter((t) => t.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al eliminar el documento');
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section className="flex flex-col gap-4">
      <div>
        <div className="t-up mb-1">Documentos de referencia</div>
        <p className="text-12 text-ink-4">
          Sube memorias técnicas previas, plantillas o ejemplos. La IA aprenderá su estructura, tono y propuesta de valor
          para redactar nuevas memorias con tu estilo. Formatos aceptados: PDF y DOCX.
        </p>
      </div>

      <div>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="hidden"
          onChange={onFileChange}
        />
        <button
          type="button"
          className="btn primary"
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? 'Procesando documento…' : 'Subir nueva referencia'}
        </button>
        {uploading && (
          <span className="ml-3 text-12 text-ink-4">
            Esto puede tardar 10–30 s mientras la IA analiza el documento.
          </span>
        )}
      </div>

      {error && (
        <div className="text-12 text-red-500 bg-red-50 border border-red-200 rounded px-3 py-2">
          {error}
        </div>
      )}

      {templates === null ? (
        <div className="flex flex-col gap-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-12 bg-surface-2 rounded animate-pulse" />
          ))}
        </div>
      ) : templates.length === 0 ? (
        <div className="text-12 text-ink-4 italic">
          Aún no has subido ningún documento de referencia.
        </div>
      ) : (
        <ul className="flex flex-col divide-y divide-ink-6 border border-ink-6 rounded">
          {templates.map((t) => (
            <li key={t.id} className="flex items-center justify-between px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="text-13 truncate">{t.title || t.filename}</div>
                <div className="text-11 text-ink-4 mt-0.5 flex gap-3 items-center">
                  <span>{t.filename}</span>
                  {t.page_count != null && <span>{t.page_count} págs.</span>}
                  {t.file_size != null && <span>{formatFileSize(t.file_size)}</span>}
                  <span className={t.has_summary ? 'text-green-700' : 'text-amber-600'}>
                    {t.has_summary ? 'Analizado' : 'Sin análisis'}
                  </span>
                </div>
              </div>
              <button
                type="button"
                className="text-12 text-ink-4 hover:text-red-600 disabled:opacity-40"
                onClick={() => onDelete(t.id)}
                disabled={deletingId === t.id}
              >
                {deletingId === t.id ? 'Eliminando…' : 'Eliminar'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


// ── TagInput component ──

interface TagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

function TagInput({ tags, onChange, placeholder }: TagInputProps) {
  const [input, setInput] = useState('');

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const value = input.trim();
      if (value && !tags.includes(value)) {
        onChange([...tags, value]);
      }
      setInput('');
    }
    if (e.key === 'Backspace' && !input && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  }

  function removeTag(index: number) {
    onChange(tags.filter((_, i) => i !== index));
  }

  return (
    <div className="flex flex-wrap gap-1.5 p-2 border border-ink-6 rounded bg-white min-h-[40px] focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/30">
      {tags.map((tag, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 px-2 py-0.5 bg-surface-2 text-12 rounded"
        >
          {tag}
          <button
            type="button"
            onClick={() => removeTag(i)}
            className="text-ink-4 hover:text-ink-1 ml-0.5"
          >
            &times;
          </button>
        </span>
      ))}
      <input
        className="flex-1 min-w-[120px] outline-none text-13 bg-transparent"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={tags.length === 0 ? placeholder : ''}
      />
    </div>
  );
}
