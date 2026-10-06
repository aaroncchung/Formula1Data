import { RefreshCw } from "lucide-react";

export function RetryButton({ onClick, label = "Try again" }: { onClick: () => void; label?: string }) {
  return (
    <button
      type="button"
      className="inline-flex items-center gap-2 rounded border border-line bg-white/[0.04] px-3 py-2 text-sm font-semibold text-white hover:border-aqua/60"
      onClick={onClick}
    >
      <RefreshCw size={16} aria-hidden="true" />
      {label}
    </button>
  );
}
