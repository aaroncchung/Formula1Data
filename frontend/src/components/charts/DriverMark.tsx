import type { DriverStyle } from "@/lib/driver-style";

export type DriverMarkKind = "line" | "dot";

/** A legend sample of how a driver is drawn: a stretch of line, or one marker. */
export function DriverMark({ style, mark, muted = false }: { style: DriverStyle; mark: DriverMarkKind; muted?: boolean }) {
  if (mark === "line") {
    return (
      <svg width="24" height="8" viewBox="0 0 24 8" aria-hidden="true" opacity={muted ? 0.35 : 1}>
        <line x1="1" y1="4" x2="23" y2="4" stroke={style.color} strokeWidth="2" strokeDasharray={style.dash} />
      </svg>
    );
  }
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" opacity={muted ? 0.35 : 1}>
      <circle
        cx="5"
        cy="5"
        r="3.25"
        fill={style.hollow ? "none" : style.color}
        stroke={style.color}
        strokeWidth="1.5"
      />
    </svg>
  );
}
