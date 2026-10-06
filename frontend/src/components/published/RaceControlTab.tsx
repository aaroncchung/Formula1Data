"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { RaceControlFeed } from "@/components/session/RaceControlFeed";
import { readRaceControl } from "@/lib/published/artifacts";

export function RaceControlTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="race-control" name="race control messages" read={readRaceControl}>
      {(messages) =>
        messages.length === 0 ? (
          <EmptyState title="No race control messages" detail="This session was published without any." />
        ) : (
          <ChartPanel title="Race Control Feed" description={`${messages.length} messages, in the order race control sent them.`}>
            <RaceControlFeed messages={messages} />
          </ChartPanel>
        )
      }
    </SessionTab>
  );
}
