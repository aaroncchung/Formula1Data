"use client";

import clsx from "clsx";
import {
  Activity,
  BarChart3,
  CalendarDays,
  Car,
  CircuitBoard,
  Flag,
  Gauge,
  LineChart,
  Radio,
  Settings,
  Trophy,
  Users
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { APP_NAME, NAV_ITEMS } from "@/lib/constants";

const iconMap = {
  Dashboard: Gauge,
  Seasons: CalendarDays,
  Telemetry: LineChart,
  Strategy: Flag,
  Standings: Trophy,
  Drivers: Users,
  Teams: Car,
  Circuits: CircuitBoard,
  Live: Radio,
  Settings: Settings
};

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex h-full flex-col">
      <div className="border-b border-line/70 px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded border border-redline/50 bg-redline/15 text-redline">
            <Activity size={22} />
          </div>
          <div>
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-400">F1 Analytics</div>
            <div className="text-lg font-black text-white">{APP_NAME}</div>
          </div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const Icon = iconMap[item.label as keyof typeof iconMap] || BarChart3;
          const active =
            item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex items-center gap-3 rounded px-3 py-2.5 text-sm font-medium transition",
                active
                  ? "bg-redline/15 text-white ring-1 ring-redline/30"
                  : "text-slate-400 hover:bg-white/5 hover:text-white"
              )}
            >
              <Icon size={18} />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-line/70 px-5 py-4 text-xs text-slate-500">
        Data artifacts are served by the FastAPI backend.
      </div>
    </aside>
  );
}

