"use client";

import { ChartPanel } from "@/components/charts/ChartPanel";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { SessionTab, type TabProps } from "@/components/published/SessionTab";
import { PositionReplay } from "@/components/session/PositionReplay";
import { readPositionReplay } from "@/lib/published/artifacts";
import { replayFrameCount } from "@/lib/track-map";

/**
 * The replay is the largest file of a session outside its telemetry. It is
 * read here and nowhere else, so a visit that never opens this tab never
 * pays for it.
 */
export function PositionReplayTab(props: TabProps) {
  return (
    <SessionTab {...props} tab="position-replay" name="position replay" read={readPositionReplay}>
      {({ replay, drivers, corners }) =>
        replayFrameCount(replay) === 0 ? (
          <EmptyState title="Position replay unavailable" detail="This session was published without car positions." />
        ) : (
          <ChartPanel title="Position Replay" description="Where each car was on the circuit, frame by frame, from the position feed.">
            <PositionReplay replay={replay} drivers={drivers} corners={corners} />
          </ChartPanel>
        )
      }
    </SessionTab>
  );
}
