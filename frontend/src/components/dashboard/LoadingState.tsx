export function LoadingState({ label = "Loading data" }: { label?: string }) {
  return (
    <div className="rounded border border-line bg-panel p-6">
      <div className="h-3 w-40 animate-pulse rounded bg-slate-700" />
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="h-20 animate-pulse rounded bg-white/[0.04]" />
        <div className="h-20 animate-pulse rounded bg-white/[0.04]" />
        <div className="h-20 animate-pulse rounded bg-white/[0.04]" />
      </div>
      <div className="mt-4 text-sm text-slate-500">{label}</div>
    </div>
  );
}

