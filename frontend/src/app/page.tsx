import { HomeDashboard } from "@/components/home/HomeDashboard";

/**
 * The home page is a static shell. What it shows is read in the browser from
 * published data, so nothing about any session is fixed when the site is
 * built.
 */
export default function DashboardPage() {
  return <HomeDashboard />;
}
