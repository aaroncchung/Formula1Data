import { ChartPanel } from "@/components/charts/ChartPanel";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { staticDataBasePath } from "@/lib/api";

export default function SettingsPage() {
  return (
    <div>
      <PageHeader title="Settings" description="Static configuration visible to the frontend." />
      <div className="grid gap-5 lg:grid-cols-2">
        <ChartPanel title="Frontend">
          <div className="space-y-3 text-sm text-slate-300">
            <div className="flex justify-between gap-3 border-b border-line pb-2">
              <span>Static data path</span>
              <span className="truncate font-mono text-aqua">{staticDataBasePath()}</span>
            </div>
            <div className="flex justify-between gap-3 border-b border-line pb-2">
              <span>Framework</span>
              <span>Next.js App Router</span>
            </div>
            <div className="flex justify-between gap-3">
              <span>Charting</span>
              <span>Recharts</span>
            </div>
          </div>
        </ChartPanel>
        <ChartPanel title="Pipeline">
          <div className="space-y-3 text-sm text-slate-300">
            <div className="flex justify-between gap-3 border-b border-line pb-2">
              <span>Artifact root</span>
              <span className="font-mono">/data</span>
            </div>
            <div className="flex justify-between gap-3 border-b border-line pb-2">
              <span>Storage</span>
              <span>Committed static JSON</span>
            </div>
            <div className="flex justify-between gap-3">
              <span>Live mode</span>
              <span>Optional future work</span>
            </div>
          </div>
        </ChartPanel>
      </div>
    </div>
  );
}
