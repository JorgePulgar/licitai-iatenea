import type { PliegoStatus, LicitacionStatus } from '../../types/licitacion';

type StatusType = PliegoStatus | LicitacionStatus;

const STATUS_MAP: Record<string, { cls: string; dotCls: string; label: string }> = {
  uploaded:      { cls: '',      dotCls: 'idle', label: 'En cola' },
  processing:    { cls: 'info',  dotCls: 'proc', label: 'Procesando' },
  indexed:       { cls: 'ok',    dotCls: 'ok',   label: 'Listo' },
  error:         { cls: 'err',   dotCls: 'err',  label: 'Error' },
  partial_error: { cls: 'warn',  dotCls: 'warn', label: 'Parcial' },
};

interface StateTagProps {
  status: StatusType;
}

export default function StateTag({ status }: StateTagProps) {
  const { cls, dotCls, label } = STATUS_MAP[status] ?? { cls: '', dotCls: 'idle', label: status };
  return (
    <span className={`tag ${cls}`}>
      <span className={`dot ${dotCls}`} />
      {label}
    </span>
  );
}
