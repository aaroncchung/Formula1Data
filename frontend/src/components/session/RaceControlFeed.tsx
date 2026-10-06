import { formatSessionClock } from "@/lib/durations";
import type { RaceControlMessage } from "@/lib/published/types";

/**
 * Race control's messages, each with when it was sent on the session clock.
 * A message's own text often quotes a time of day at the circuit ("TIMED AT
 * 16:30:20"); the clock here is labelled as the session's so the two are not
 * read as a disagreement.
 */
export function RaceControlFeed({ messages }: { messages: ReadonlyArray<RaceControlMessage> }) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        Times are the session clock in hours, minutes and seconds, which starts with F1&apos;s timing feed and not with
        the session.
      </p>
      {messages.map((message, index) => (
        <div key={index} className="rounded border border-line bg-white/[0.03] p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="font-mono" title="Session clock">{formatSessionClock(message.time_ms)}</span>
            <span>Lap {message.lap_number ?? "--"}</span>
            <span className="rounded border border-line px-2 py-0.5 text-slate-300">{message.category}</span>
            {message.flag ? <span className="font-bold text-amber">{message.flag}</span> : null}
            {message.scope ? <span>{message.scope}</span> : null}
          </div>
          <div className="mt-2 text-sm text-slate-100">{message.message}</div>
        </div>
      ))}
    </div>
  );
}
