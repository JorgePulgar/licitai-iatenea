import { useState } from 'react';
import type { LicitacionResponse } from '../../types/licitacion';
import { updateLicitacion } from '../../services/api';
import {
  COMMERCIAL_OPTIONS,
  commercialOptionByKey,
  resolveCommercialOption,
} from '../../utils/commercialState';

interface CommercialStateEditorProps {
  licitacion: LicitacionResponse;
  onUpdated: (updated: LicitacionResponse) => void;
}

/**
 * Editor inline del estado comercial y la fecha límite. Cada cambio persiste vía
 * PATCH y propaga la licitación actualizada al padre. Solo se usa en el detalle.
 */
export default function CommercialStateEditor({ licitacion, onUpdated }: CommercialStateEditorProps) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentKey = resolveCommercialOption(licitacion.estado, licitacion.resultado).key;

  async function handleEstadoChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const opt = commercialOptionByKey(e.target.value);
    if (!opt) return;
    await persist({ estado: opt.estado, resultado: opt.resultado });
  }

  async function handleDeadlineChange(e: React.ChangeEvent<HTMLInputElement>) {
    await persist({ deadline: e.target.value || null });
  }

  async function persist(patch: Parameters<typeof updateLicitacion>[1]) {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateLicitacion(licitacion.id, patch);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <label className="flex items-center gap-1.5 t-xs t-mute">
        Estado
        <select
          className="real-input py-1 text-12"
          value={currentKey}
          onChange={handleEstadoChange}
          disabled={saving}
        >
          {COMMERCIAL_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-1.5 t-xs t-mute">
        Fecha límite
        <input
          type="date"
          className="real-input py-1 text-12"
          value={licitacion.deadline ?? ''}
          onChange={handleDeadlineChange}
          disabled={saving}
        />
      </label>

      {saving && <span className="t-xs t-mute">Guardando…</span>}
      {error && <span className="t-xs text-err" title={error}>Error al guardar</span>}
    </div>
  );
}
