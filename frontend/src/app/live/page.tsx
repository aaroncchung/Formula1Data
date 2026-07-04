import { PageHeader } from "@/components/dashboard/PageHeader";
import { LiveDataPanel } from "@/components/live/LiveDataPanel";

export default async function LivePage() {
  return (
    <div>
      <PageHeader
        title="Live"
        description="Live timing uses the optional Cloudflare Worker API. Static-only deployments keep historical browsing available from committed JSON artifacts."
      />
      <LiveDataPanel />
    </div>
  );
}
