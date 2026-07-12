type ChartPanelProps = {
  title: string;
  description?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
};

export function ChartPanel({ title, description, children, action, className = "" }: ChartPanelProps) {
  return (
    <section className={`surface p-4 sm:p-5 ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-bold tracking-tight text-white">{title}</h2>
          {description ? <p className="mt-1 max-w-4xl text-sm leading-5 text-slate-400">{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

