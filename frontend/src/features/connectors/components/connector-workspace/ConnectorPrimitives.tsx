

export function ConnectorStatusPill({ className, label, minWidth }: { className: string; label: string; minWidth?: string }) {
  return <span className={`${className} justify-center whitespace-nowrap`} style={minWidth ? { minWidth } : undefined}>{label}</span>;
}

export function ConnectorEmptyState({ detail, title }: { detail: string; title: string }) {
  return (
    <div className="rounded-md border border-dashed border-surface-border bg-surface p-3 text-body-md text-on-surface-variant">
      <p className="font-bold text-on-surface">{title}</p>
      <p className="mt-1">{detail}</p>
    </div>
  );
}
