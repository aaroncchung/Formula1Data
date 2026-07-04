import { ErrorState } from "@/components/dashboard/ErrorState";
import { PageHeader } from "@/components/dashboard/PageHeader";
import { api, safeApi } from "@/lib/api-server";

export default async function CircuitsPage() {
  const catalog = await safeApi(() => api.catalog());
  if (!catalog.ok) {
    return <ErrorState title="Could not load circuits" detail={`${catalog.error.message}: ${catalog.apiBaseUrl}`} />;
  }
  return (
    <div>
      <PageHeader title="Circuits" description="Circuit metadata from season meeting artifacts." />
      <div className="grid gap-4 md:grid-cols-2">
        {catalog.data.meetings.map((meeting) => (
          <div key={meeting.circuit.circuit_id} className="rounded border border-line bg-panel p-5">
            <div className="text-xs font-bold uppercase tracking-[0.16em] text-redline">Round {meeting.round}</div>
            <div className="mt-2 text-xl font-black text-white">{meeting.circuit.name}</div>
            <div className="mt-1 text-sm text-slate-400">{meeting.circuit.location || meeting.country}</div>
            <div className="mt-4 text-sm text-slate-300">{meeting.name}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
