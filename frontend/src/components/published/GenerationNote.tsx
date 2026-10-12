import Link from "next/link";

import { compactDate } from "@/lib/format";
import type { SessionView } from "@/lib/published/client";

/**
 * Which publication is on screen: everything above was read from this one
 * generation. A page reached by year and round also offers its address by
 * key, which is the one to keep: a round names another race once the calendar
 * moves (AR-20).
 */
export function GenerationNote({ view, permanentHref }: { view: SessionView; permanentHref: string | null }) {
  const { pointer, manifest } = view;
  return (
    <p className="mt-6 text-xs text-slate-600">
      Published {compactDate(pointer.published_at)} · generation{" "}
      <span className="font-mono">{pointer.generation.slice(0, 12)}</span> · {manifest.files.length} files · session key{" "}
      <span className="font-mono">{pointer.session_key}</span>
      {permanentHref ? (
        <>
          {" · "}
          <Link className="text-slate-400 underline decoration-slate-600 underline-offset-2 hover:text-white" href={permanentHref}>
            Permanent link
          </Link>
        </>
      ) : null}
    </p>
  );
}
