type MetricCardProps = {
  label: string;
  value: string | number;
  detail?: string;
  tone?: "red" | "aqua" | "amber" | "neutral";
};

const toneClass = {
  red: "text-redline",
  aqua: "text-aqua",
  amber: "text-amber",
  neutral: "text-slate-100"
};

export function MetricCard({ label, value, detail, tone = "neutral" }: MetricCardProps) {
  return (
    <div className="rounded border border-line bg-panel p-4 shadow-panel">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className={`mt-3 text-2xl font-black ${toneClass[tone]}`}>{value}</div>
      {detail ? <div className="mt-2 text-sm text-slate-400">{detail}</div> : null}
    </div>
  );
}

