import type { LicitacionEstado } from '../types/licitacion';

// Tono visual reutilizando las clases de `tag`/`dot` ya existentes (StateTag).
export type CommercialTone = 'idle' | 'info' | 'warn' | 'ok' | 'err';

/**
 * Opción comercial seleccionable en la UI. El estado terminal "resuelta" se
 * desdobla en dos opciones (Ganada / Perdida) mediante el booleano `resultado`,
 * tal como se acordó: un único estado con resultado booleano.
 */
export interface CommercialOption {
  key: string;                 // clave única de UI
  label: string;
  estado: LicitacionEstado;
  resultado: boolean | null;
  tone: CommercialTone;
}

export const COMMERCIAL_OPTIONS: CommercialOption[] = [
  { key: 'elaborando',         label: 'Elaborando',           estado: 'elaborando',         resultado: null,  tone: 'idle' },
  { key: 'revision_comercial', label: 'En revisión comercial', estado: 'revision_comercial', resultado: null,  tone: 'info' },
  { key: 'entregada',          label: 'Entregada',            estado: 'entregada',          resultado: null,  tone: 'warn' },
  { key: 'ganada',             label: 'Ganada',               estado: 'resuelta',           resultado: true,  tone: 'ok' },
  { key: 'perdida',            label: 'Perdida',              estado: 'resuelta',           resultado: false, tone: 'err' },
];

/** Resuelve la opción comercial a partir del par (estado, resultado) del backend. */
export function resolveCommercialOption(
  estado: LicitacionEstado,
  resultado: boolean | null,
): CommercialOption {
  if (estado === 'resuelta') {
    return resultado ? COMMERCIAL_OPTIONS[3] : COMMERCIAL_OPTIONS[4];
  }
  return COMMERCIAL_OPTIONS.find((o) => o.estado === estado) ?? COMMERCIAL_OPTIONS[0];
}

/** Busca una opción por su clave de UI. */
export function commercialOptionByKey(key: string): CommercialOption | undefined {
  return COMMERCIAL_OPTIONS.find((o) => o.key === key);
}
