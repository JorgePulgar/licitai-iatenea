import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import { useId } from "react";

type FieldWrapperProps = {
  label: string;
  error?: string;
  help?: string;
};

const FIELD_CLASSES =
  "w-full rounded border border-line bg-surface px-3 py-2 text-sm text-ink-1 placeholder:text-ink-3 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:bg-bg";

export function Input({
  label,
  error,
  help,
  ...rest
}: FieldWrapperProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-ink-2">
        {label}
      </label>
      <input id={id} className={FIELD_CLASSES} aria-invalid={!!error} {...rest} />
      {error && <p className="text-sm text-danger">{error}</p>}
      {help && !error && <p className="text-sm text-ink-3">{help}</p>}
    </div>
  );
}

export function Textarea({
  label,
  error,
  help,
  ...rest
}: FieldWrapperProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-ink-2">
        {label}
      </label>
      <textarea id={id} className={FIELD_CLASSES} aria-invalid={!!error} {...rest} />
      {error && <p className="text-sm text-danger">{error}</p>}
      {help && !error && <p className="text-sm text-ink-3">{help}</p>}
    </div>
  );
}
