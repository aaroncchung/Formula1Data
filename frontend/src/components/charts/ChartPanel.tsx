type ChartPanelProps = {
  title: string;
  description?: string;
  children: React.ReactNode;
};

export function ChartPanel({ title, description, children }: ChartPanelProps) {
  return (
    <section className="rounded border border-line bg-panel p-4 shadow-panel">
      <div className="mb-4">
        <h2 className="text-base font-bold text-white">{title}</h2>
        {description ? <p className="mt-1 text-sm text-slate-400">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

