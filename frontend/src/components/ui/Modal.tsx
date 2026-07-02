import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  Info,
  KeyRound,
  X,
} from 'lucide-react';

export type ModalTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
export type ModalSize = 'sm' | 'md' | 'lg' | 'xl';

interface BaseModalOptions {
  title: ReactNode;
  description?: ReactNode;
  tone?: ModalTone;
  size?: ModalSize;
  dismissible?: boolean;
}

export interface AlertModalOptions extends BaseModalOptions {
  type: 'alert';
  confirmLabel?: string;
}

export interface ConfirmationModalOptions extends BaseModalOptions {
  type: 'confirmation';
  confirmLabel?: string;
  cancelLabel?: string;
}

export interface PermissionModalOptions extends BaseModalOptions {
  type: 'permission';
  confirmLabel?: string;
  cancelLabel?: string;
}

export interface CustomModalControls<T> {
  close: (value: T) => void;
  dismiss: () => void;
}

export interface CustomModalOptions<T = unknown> extends BaseModalOptions {
  type: 'custom';
  content: ReactNode | ((controls: CustomModalControls<T>) => ReactNode);
  footer?: ReactNode | ((controls: CustomModalControls<T>) => ReactNode);
  dismissValue?: T;
}

export type ModalOptions<T = unknown> =
  | AlertModalOptions
  | ConfirmationModalOptions
  | PermissionModalOptions
  | CustomModalOptions<T>;

interface ModalProps {
  options: ModalOptions<unknown>;
  onResolve: (value: unknown) => void;
  onDismiss: () => void;
}

const SIZE_CLASSES: Record<ModalSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

const TONE_CLASSES: Record<ModalTone, string> = {
  neutral: 'bg-surface-2 text-ink-2',
  info: 'bg-info-bg text-info',
  success: 'bg-ok-bg text-ok',
  warning: 'bg-warn-bg text-warn',
  danger: 'bg-err-bg text-err',
};

const PRIMARY_CLASSES: Record<ModalTone, string> = {
  neutral: 'primary',
  info: 'info-solid',
  success: 'success-solid',
  warning: 'warning-solid',
  danger: 'danger-solid',
};

function ToneIcon({ tone, type }: { tone: ModalTone; type: ModalOptions['type'] }) {
  const props = { size: 20, 'aria-hidden': true };
  if (type === 'permission') return <KeyRound {...props} />;
  if (tone === 'danger') return <CircleAlert {...props} />;
  if (tone === 'warning') return <AlertTriangle {...props} />;
  if (tone === 'success') return <CheckCircle2 {...props} />;
  return <Info {...props} />;
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), ' +
      'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter(element => !element.hasAttribute('hidden'));
}

function renderCustomSlot(
  slot: ReactNode | ((controls: CustomModalControls<unknown>) => ReactNode) | undefined,
  controls: CustomModalControls<unknown>,
): ReactNode {
  return typeof slot === 'function' ? slot(controls) : slot;
}

export default function Modal({ options, onResolve, onDismiss }: ModalProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const dismissible = options.dismissible ?? options.type === 'custom';
  const tone = options.tone ?? 'neutral';
  const size = options.size ?? 'md';

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const dialog = dialogRef.current;
    const focusable = dialog ? focusableElements(dialog) : [];
    const initialFocus = dialog?.querySelector<HTMLElement>('[data-modal-initial-focus]');
    (initialFocus ?? focusable[0] ?? dialog)?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && dismissible) {
        event.preventDefault();
        onDismiss();
        return;
      }
      if (event.key !== 'Tab' || !dialog) return;

      const elements = focusableElements(dialog);
      if (elements.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [dismissible, onDismiss]);

  const controls: CustomModalControls<unknown> = {
    close: onResolve,
    dismiss: onDismiss,
  };

  const customOptions = options.type === 'custom' ? options : null;
  const standardOptions = options.type === 'custom' ? null : options;
  const customContent = customOptions
    ? renderCustomSlot(customOptions.content, controls)
    : null;
  const customFooter = customOptions
    ? renderCustomSlot(customOptions.footer, controls)
    : null;

  return createPortal(
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/45 p-4 backdrop-blur-[1px]"
      onMouseDown={event => {
        if (dismissible && event.target === event.currentTarget) onDismiss();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={options.description ? descriptionId : undefined}
        tabIndex={-1}
        className={`w-full ${SIZE_CLASSES[size]} max-h-[calc(100vh-2rem)] overflow-hidden rounded-md border border-line-strong bg-surface shadow-2xl outline-none`}
      >
        <div className="flex items-start gap-3 border-b border-line px-4 py-3">
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${TONE_CLASSES[tone]}`}>
            <ToneIcon tone={tone} type={options.type} />
          </div>
          <div className="min-w-0 flex-1 pt-0.5">
            <div id={titleId} className="text-14 font-semibold text-ink">
              {options.title}
            </div>
            {options.description && (
              <div id={descriptionId} className="mt-1 text-12 text-ink-3">
                {options.description}
              </div>
            )}
          </div>
          {dismissible && (
            <button
              type="button"
              className="btn ghost h-7 w-7 justify-center p-0"
              onClick={onDismiss}
              aria-label="Cerrar modal"
            >
              <X size={15} />
            </button>
          )}
        </div>

        {customOptions && (
          <div className="max-h-[calc(100vh-11rem)] overflow-y-auto p-4">
            {customContent}
          </div>
        )}

        {customOptions ? (
          customFooter && (
            <div className="flex items-center justify-end gap-2 border-t border-line bg-surface-2 px-4 py-3">
              {customFooter}
            </div>
          )
        ) : standardOptions && (
          <div className="flex items-center justify-end gap-2 bg-surface-2 px-4 py-3">
            {(standardOptions.type === 'confirmation' || standardOptions.type === 'permission') && (
              <button type="button" className="btn" onClick={onDismiss}>
                {standardOptions.cancelLabel ?? (standardOptions.type === 'permission' ? 'Ahora no' : 'Cancelar')}
              </button>
            )}
            <button
              type="button"
              className={`btn ${PRIMARY_CLASSES[tone]}`}
              data-modal-initial-focus
              onClick={() => onResolve(standardOptions.type === 'alert' ? undefined : true)}
            >
              {standardOptions.confirmLabel ?? (
                standardOptions.type === 'permission' ? 'Permitir' : standardOptions.type === 'alert' ? 'Aceptar' : 'Confirmar'
              )}
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
