"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { PositionReplay } from "@/components/session/PositionReplay";
import { readPositionReplay } from "@/lib/published/artifacts";

/**
 * The replay is megabytes of positions, far more than the rest of a session
 * outside its telemetry. It is read here and nowhere else, so a visit that
 * never opens this tab never pays for it.
 */
export function PositionReplayTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="position-replay" name="position replay" read={readPositionReplay}>
      {({ frames, drivers }) =>
        frames.length === 0 ? (
          <EmptyState title="Position replay unavailable" detail="This session was published without car positions." />
        ) : (
          <ChartPanel title="Position Replay" description="Where each car was on the circuit, frame by frame, from the position feed.">
            <PositionReplay frames={frames} drivers={drivers} />
          </ChartPanel>
        )
      }
    </SessionTab>
  );
}
