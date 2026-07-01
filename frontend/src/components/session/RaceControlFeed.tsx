import type { RaceControlMessage } from "@/types/domain";

export function RaceControlFeed({ messages }: { messages: RaceControlMessage[] }) {
  return (
    <div className="space-y-3">
      {messages.map((message, index) => (
        <div key={`${message.timestamp}-${index}`} className="rounded border border-line bg-white/[0.03] p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{message.timestamp || "--"}</span>
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

