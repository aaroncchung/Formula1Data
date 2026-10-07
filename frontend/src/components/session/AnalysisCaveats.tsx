/** The method notes an analysis publishes with its result, shown under it. */
export function AnalysisCaveats({ caveats }: { caveats?: ReadonlyArray<string> }) {
  if (!caveats?.length) {
    return null;
  }
  return (
    <p className="mt-4 rounded-md border border-amber/20 bg-amber/5 p-3 text-xs leading-5 text-slate-400">
      <span className="font-bold text-amber">Method note: </span>
      {caveats.join(" ")}
    </p>
  );
}
