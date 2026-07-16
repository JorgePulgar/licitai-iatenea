type Tab = { id: string; label: string };

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-line">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={tab.id === active}
          onClick={() => onChange(tab.id)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors duration-150 ${
            tab.id === active
              ? "border-accent text-accent"
              : "border-transparent text-ink-2 hover:text-ink-1"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
