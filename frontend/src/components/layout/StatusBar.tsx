interface StatusBarProps {
  items?: string[];
}

export default function StatusBar({ items = [] }: StatusBarProps) {
  const allItems = ['Modo desarrollo — autenticación pendiente', ...items];

  return (
    <div className="statusbar">
      {allItems.map((it, i) => (
        <span key={i} className="flex items-center gap-4">
          {i > 0 && <span className="sep">·</span>}
          <span>{it}</span>
        </span>
      ))}
      <div className="flex-1" />
      <span>v0.4.2 · entorno: licitai-dev</span>
    </div>
  );
}
