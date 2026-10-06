"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { WeatherTimeline } from "@/components/session/WeatherTimeline";
import { readWeather } from "@/lib/published/artifacts";

export function WeatherTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="weather" name="weather" read={readWeather}>
      {(samples) =>
        samples.length === 0 ? (
          <EmptyState title="No weather samples" detail="This session was published without weather data." />
        ) : (
          <ChartPanel title="Weather Timeline" description="Air and track temperature through the session.">
            <WeatherTimeline samples={samples} />
          </ChartPanel>
        )
      }
    </SessionTab>
  );
}
