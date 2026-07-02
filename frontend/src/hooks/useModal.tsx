import { createContext, useCallback, useContext, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import Modal from '../components/ui/Modal';
import type {
  AlertModalOptions,
  ConfirmationModalOptions,
  CustomModalOptions,
  ModalOptions,
  PermissionModalOptions,
} from '../components/ui/Modal';

export interface ShowModal {
  /** Un botón. Resuelve cuando el usuario acepta. */
  (options: AlertModalOptions): Promise<void>;
  /** Cancelar resuelve `false`; confirmar resuelve `true`. */
  (options: ConfirmationModalOptions): Promise<boolean>;
  /** Variante semántica de confirmación para solicitar permisos. */
  (options: PermissionModalOptions): Promise<boolean>;
  /** Renderiza TSX arbitrario y devuelve el valor entregado a `controls.close(value)`. */
  <T>(options: CustomModalOptions<T>): Promise<T | undefined>;
}

interface PendingModal {
  id: number;
  options: ModalOptions<unknown>;
  resolve: (value: unknown) => void;
}

interface ModalContextValue {
  showModal: ShowModal;
}

const ModalContext = createContext<ModalContextValue | null>(null);

export function ModalProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<PendingModal | null>(null);
  const currentRef = useRef<PendingModal | null>(null);
  const queueRef = useRef<PendingModal[]>([]);
  const nextIdRef = useRef(1);

  const present = useCallback((pending: PendingModal | null) => {
    currentRef.current = pending;
    setCurrent(pending);
  }, []);

  const finish = useCallback((value: unknown) => {
    const active = currentRef.current;
    if (!active) return;

    active.resolve(value);
    present(queueRef.current.shift() ?? null);
  }, [present]);

  const dismiss = useCallback(() => {
    const active = currentRef.current;
    if (!active) return;

    const { options } = active;
    if (options.type === 'confirmation' || options.type === 'permission') {
      finish(false);
    } else if (options.type === 'custom') {
      finish(options.dismissValue);
    } else {
      finish(undefined);
    }
  }, [finish]);

  const showModal = useCallback((options: ModalOptions<unknown>) => (
    new Promise<unknown>(resolve => {
      const pending = { id: nextIdRef.current++, options, resolve };
      if (currentRef.current) {
        queueRef.current.push(pending);
      } else {
        present(pending);
      }
    })
  ), [present]) as ShowModal;

  return (
    <ModalContext.Provider value={{ showModal }}>
      {children}
      {current && (
        <Modal
          key={current.id}
          options={current.options}
          onResolve={finish}
          onDismiss={dismiss}
        />
      )}
    </ModalContext.Provider>
  );
}

export function useModal(): ModalContextValue {
  const context = useContext(ModalContext);
  if (!context) {
    throw new Error('useModal debe usarse dentro de <ModalProvider>');
  }
  return context;
}
