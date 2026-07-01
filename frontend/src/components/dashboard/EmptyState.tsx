import { Info } from "lucide-react";

export function EmptyState({ title, detail, action }: { title: string; detail?: string; action?: React.ReactNode }) {
  return (
    <div className="rounded border border-line bg-panel p-6 text-center">
      <div className="mx-auto grid h-10 w-10 place-items-center rounded border border-line bg-white/[0.04] text-slate-300">
        <Info size={18} />
      </div>
      <div className="mt-3 font-semibold text-white">{title}</div>
      {detail ? <div className="mx-auto mt-2 max-w-xl text-sm text-slate-400">{detail}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

