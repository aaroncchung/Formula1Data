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

const toneLineClass = {
  red: "via-redline",
  aqua: "via-aqua",
  amber: "via-amber",
  neutral: "via-slate-400"
};

export function MetricCard({ label, value, detail, tone = "neutral" }: MetricCardProps) {
  return (
    <div className="surface relative overflow-hidden p-4">
      <div className={`absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent ${toneLineClass[tone]} to-transparent opacity-70`} />
      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className={`mt-3 text-2xl font-black tabular-nums tracking-tight ${toneClass[tone]}`}>{value}</div>
      {detail ? <div className="mt-2 text-sm text-slate-400">{detail}</div> : null}
    </div>
  );
}

