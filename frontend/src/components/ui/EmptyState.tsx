interface EmptyStateProps {
  title: string;
  description?: string;
  sprint?: string;
}

export default function EmptyState({ title, description, sprint }: EmptyStateProps) {
  return (
    <div className="flex flex-col flex-1 items-center justify-center gap-3 p-12 text-ink-3">
      <div className="w-10 h-10 border border-dashed border-line-strong rounded flex items-center justify-center text-18 text-ink-4">
        ⏳
      </div>
      <div className="text-center max-w-[420px]">
        <div className="t-medium text-13 text-ink-2 mb-[6px]">{title}</div>
        {description && <p className="help leading-relaxed">{description}</p>}
        {sprint && (
          <div className="mt-[10px]">
            <span className="tag info mono">{sprint}</span>
          </div>
        )}
      </div>
    </div>
  );
}
