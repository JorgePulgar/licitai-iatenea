import type { LicitacionEstado } from '../../types/licitacion';
import { resolveCommercialOption, type CommercialTone } from '../../utils/commercialState';

const TONE_CLS: Record<CommercialTone, string> = {
  idle: '',
  info: 'info',
  warn: 'warn',
  ok: 'ok',
  err: 'err',
};

interface CommercialStateBadgeProps {
  estado: LicitacionEstado;
  resultado: boolean | null;
}

/** Badge de solo lectura para el estado comercial de una licitación. */
export default function CommercialStateBadge({ estado, resultado }: CommercialStateBadgeProps) {
  const opt = resolveCommercialOption(estado, resultado);
  const cls = TONE_CLS[opt.tone];
  return (
    <span className={`tag ${cls}`}>
      <span className={`dot ${opt.tone}`} />
      {opt.label}
    </span>
  );
}
