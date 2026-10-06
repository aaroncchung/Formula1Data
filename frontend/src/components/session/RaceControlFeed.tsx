import { clockTimeOfTimestamp } from "@/lib/pandas-time";
import type { RaceControlMessage } from "@/types/domain";

export function RaceControlFeed({ messages }: { messages: RaceControlMessage[] }) {
  return (
    <div className="space-y-3">
      {messages.map((message, index) => (
        <div key={`${message.timestamp}-${index}`} className="rounded border border-line bg-white/[0.03] p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="font-mono">{messageTime(message.timestamp)}</span>
            <span>Lap {message.lap_number || "--"}</span>
            <span className="rounded border border-line px-2 py-0.5 text-slate-300">{message.category}</span>
            {message.flag ? <span className="font-bold text-amber">{message.flag}</span> : null}
          </div>
          <div className="mt-2 text-sm text-slate-100">{message.message}</div>
        </div>
      ))}
    </div>
  );
}

/**
 * The time of day of a message. F1's feed is in UTC and the artifact drops
 * the zone, so it is named here; a message's own text often quotes the local
 * time ("TIMED AT 16:30:20"), and the two would otherwise look like a
 * disagreement.
 */
function messageTime(timestamp: string | null | undefined): string {
  const time = clockTimeOfTimestamp(timestamp);
  if (time) {
    return `${time} UTC`;
  }
  return timestamp || "--";
}
