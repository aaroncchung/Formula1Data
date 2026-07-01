import { EmptyState } from "@/components/dashboard/EmptyState";
import { isLiveDisabled } from "@/lib/api";
import type { LiveDisabledResponse } from "@/types/domain";

export function LiveTimingBoard({ payload }: { payload: Record<string, unknown> | LiveDisabledResponse }) {
  if (isLiveDisabled(payload)) {
    return (
      <EmptyState
        title="Live mode is disabled"
        detail={`${payload.reason} ${payload.setup.join(" ")}`}
      />
    );
  }
  return (
    <pre className="max-h-[520px] overflow-auto rounded border border-line bg-panel p-4 text-xs text-slate-300">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}

