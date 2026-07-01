import { AlertTriangle } from "lucide-react";

export function ErrorState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="rounded border border-redline/40 bg-redline/10 p-5">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 text-redline" size={18} />
        <div>
          <div className="font-semibold text-white">{title}</div>
          {detail ? <div className="mt-1 text-sm text-slate-300">{detail}</div> : null}
        </div>
      </div>
    </div>
  );
}

