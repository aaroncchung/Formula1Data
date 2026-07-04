import { PageHeader } from "@/components/dashboard/PageHeader";
import { LiveDataPanel } from "@/components/live/LiveDataPanel";

export default async function LivePage() {
  return (
    <div>
      <PageHeader title="Live" description="OpenF1 live data through the server-side Cloudflare Worker proxy." />
      <LiveDataPanel />
    </div>
  );
}
