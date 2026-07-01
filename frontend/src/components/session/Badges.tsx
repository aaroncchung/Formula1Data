import { COMPOUND_COLORS } from "@/lib/constants";

export function DriverBadge({ code, color }: { code: string; color?: string | null }) {
  return (
    <span className="inline-flex items-center gap-2 font-mono font-semibold text-white">
      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color || "#94a3b8" }} />
      {code}
    </span>
  );
}

export function TeamColorPill({ name, color }: { name: string; color?: string | null }) {
  return (
    <span className="inline-flex items-center gap-2 rounded border border-line bg-white/[0.03] px-2 py-1 text-xs text-slate-300">
      <span className="h-2 w-5 rounded" style={{ backgroundColor: color || "#64748b" }} />
      {name}
    </span>
  );
}

export function CompoundBadge({ compound }: { compound?: string | null }) {
  const label = compound || "UNKNOWN";
  return (
    <span
      className="inline-flex rounded border px-2 py-0.5 text-xs font-bold"
      style={{
        color: COMPOUND_COLORS[label] || "#94a3b8",
        borderColor: `${COMPOUND_COLORS[label] || "#94a3b8"}66`,
        backgroundColor: `${COMPOUND_COLORS[label] || "#94a3b8"}18`
      }}
    >
      {label}
    </span>
  );
}

