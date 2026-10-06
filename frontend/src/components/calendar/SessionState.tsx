import clsx from "clsx";
import { AlertTriangle, CalendarClock, CheckCircle2, CircleDashed } from "lucide-react";
import Link from "next/link";

import type { SessionAvailability } from "@/lib/calendar";
import { sessionStart } from "@/lib/format";
import { isPublished, sessionHref } from "@/lib/published/lookup";
import type { IndexSession } from "@/lib/published/types";

/**
 * How each state of a session is worded and coloured, everywhere the calendar
 * shows one. Published and complete are separate states (rule 3), so "partial"
 * has a colour of its own and is never folded into "published".
 */
const STATES: Record<
  SessionAvailability,
  { label: string; meaning: string; tone: string; icon: typeof CheckCircle2 }
> = {
  complete: {
    label: "Complete",
    meaning: "Published with complete data",
    tone: "border-aqua/40 bg-aqua/10 text-aqua",
    icon: CheckCircle2
  },
  partial: {
    label: "Partial",
    meaning: "Published with partial data: something fell short when it was fetched",
    tone: "border-amber/40 bg-amber/10 text-amber",
    icon: AlertTriangle
  },
  not_published: {
    label: "Not published",
    meaning: "This session has been run, and its data is not published",
    tone: "border-line bg-white/[0.03] text-slate-500",
    icon: CircleDashed
  },
  scheduled: {
    label: "Scheduled",
    meaning: "This session has not been run yet",
    tone: "border-line border-dashed bg-transparent text-slate-400",
    icon: CalendarClock
  }
};

export function SessionStateBadge({ state }: { state: SessionAvailability }) {
  const { label, meaning, tone, icon: Icon } = STATES[state];
  return (
    <span
      className={clsx("inline-flex items-center gap-1.5 rounded border px-2 py-1 text-xs font-semibold", tone)}
      title={meaning}
    >
      <Icon size={13} aria-hidden="true" />
      {label}
    </span>
  );
}

/**
 * One session in a meeting's row of sessions. A published session is a link
 * to its dashboard, by its key. One that is not published is text and not a
 * link: there is nothing behind it to open.
 */
export function SessionChip({ session, state }: { session: IndexSession; state: SessionAvailability }) {
  const { label, meaning, tone, icon: Icon } = STATES[state];
  const description = `${session.name}: ${meaning.charAt(0).toLowerCase()}${meaning.slice(1)}. ${sessionStart(session.start_time_utc)}`;
  const className = clsx("inline-flex items-center gap-1.5 rounded border px-2 py-1 text-xs font-semibold", tone);
  const content = (
    <>
      <span className="font-mono">{session.type}</span>
      <Icon size={12} aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </>
  );
  if (!isPublished(session)) {
    return (
      <span className={className} title={description}>
        {content}
      </span>
    );
  }
  return (
    <Link
      href={sessionHref({ kind: "key", sessionKey: session.session_key })}
      className={clsx(className, "transition hover:border-white/60 hover:text-white")}
      title={description}
    >
      {content}
    </Link>
  );
}

/** What the colours of the chips mean, for a page that shows many of them. */
export function SessionStateLegend() {
  const order: SessionAvailability[] = ["complete", "partial", "not_published", "scheduled"];
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500" aria-label="Session states">
      {order.map((state) => (
        <li key={state}>
          <SessionStateBadge state={state} />
        </li>
      ))}
    </ul>
  );
}
