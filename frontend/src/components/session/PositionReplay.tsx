"use client";

import { useMemo, useState } from "react";

import { CornerMarks } from "@/components/session/CornerMarks";
import { circuitLayout, layoutNote, trackMap, turned } from "@/lib/circuit-layout";
import { driverStyle, teamDriverStyles } from "@/lib/driver-style";
import { formatSessionClock } from "@/lib/durations";
import type { Corners, Driver, PositionReplay as Replay } from "@/lib/published/types";
import { outlinePath, replayCars, replayFrameCount, replayPositions, type Viewport } from "@/lib/track-map";

// Drawn as plain SVG, not as a chart: the viewBox keeps one scale on both
// axes at any size on screen, which chart axes do not. The padding leaves
// room for a corner's label off the outside of the track.
const VIEWPORT: Viewport = { width: 1000, height: 600, padding: 48 };
const MAP_BACKGROUND = "#0b0f17";
const CORNER_RADIUS = 11;
const CORNER_LABEL_DISTANCE = 28;

/**
 * `corners` is the circuit's own corner map, or null when the session has
 * none. Where it fits the track the map is turned the way F1 draws the
 * circuit, and its corners are numbered.
 */
export function PositionReplay({
  replay,
  drivers,
  corners
}: {
  replay: Replay;
  drivers: ReadonlyArray<Driver>;
  corners: Corners | null;
}) {
  const [chosen, setChosen] = useState(0);
  const layout = useMemo(() => circuitLayout(corners), [corners]);
  // Taken from every frame, once. Moving through the replay changes which
  // cars are drawn, never where a point on the circuit lands.
  const positions = useMemo(() => replayPositions(replay), [replay]);
  const map = useMemo(() => trackMap(positions, layout, VIEWPORT, CORNER_LABEL_DISTANCE), [positions, layout]);
  const outline = useMemo(
    () => (map ? outlinePath(positions.map((position) => turned(position, layout.rotation)), map.projection) : ""),
    [positions, layout, map]
  );
  const styles = useMemo(() => teamDriverStyles(drivers), [drivers]);

  const frames = replayFrameCount(replay);
  if (frames === 0 || !map) {
    return <div className="text-sm text-slate-400">No replay frames available.</div>;
  }
  const note = layoutNote(layout);
  // The replay can be replaced under the slider, when the session is opened
  // again on another generation; a frame it no longer has is its last.
  const index = Math.min(chosen, frames - 1);
  const cars = replayCars(replay, index);
  const unplaced = replay.drivers.length - cars.length;
  return (
    <div className="space-y-4">
      <svg
        viewBox={`0 0 ${VIEWPORT.width} ${VIEWPORT.height}`}
        className="max-h-[70vh] w-full rounded border border-line"
        style={{ backgroundColor: MAP_BACKGROUND }}
        role="img"
        aria-label={`Car positions on the circuit, frame ${index + 1} of ${frames}`}
      >
        <path d={outline} fill="none" stroke="#263042" strokeWidth="6" strokeLinecap="round" />
        {/* Under the cars, which are what moves. */}
        <CornerMarks corners={map.corners} radius={CORNER_RADIUS} />
        {cars.map((car) => {
          const at = map.place(car);
          const style = driverStyle(styles, car.driver);
          return (
            <g key={car.driver}>
              <title>
                {car.speedKph === null ? car.driver : `${car.driver} · ${Math.round(car.speedKph)} km/h`}
              </title>
              <circle
                cx={at.x}
                cy={at.y}
                r="6.5"
                fill={style.hollow ? MAP_BACKGROUND : style.color}
                stroke={style.color}
                strokeWidth="3"
              />
              <text
                x={at.x + 11}
                y={at.y + 4}
                fontSize="13"
                fontWeight="700"
                fill="#e5edf8"
                stroke={MAP_BACKGROUND}
                strokeWidth="3"
                paintOrder="stroke"
                className="font-mono"
              >
                {car.driver}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="flex items-center gap-3">
        <input
          className="w-full accent-redline"
          type="range"
          aria-label="Position replay frame"
          min={0}
          max={frames - 1}
          value={index}
          onChange={(event) => setChosen(Number(event.target.value))}
        />
        <div className="w-24 text-right font-mono text-sm text-slate-400">
          {index + 1}/{frames}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
        <span>Lap <strong className="font-mono text-slate-300">{replay.lap_number[index] ?? "--"}</strong></span>
        <span>Session clock <strong className="font-mono text-slate-300">{formatSessionClock(replay.time_ms[index])}</strong></span>
        <span>Cars <strong className="font-mono text-slate-300">{cars.length}</strong></span>
        {unplaced > 0 ? <span>{unplaced} without a position in this frame</span> : null}
        <span>A frame is {formatSeconds(replay.interval_ms)} of the session.</span>
        <span>Team-mates share a colour: one marker is filled, the other hollow.</span>
        {map.corners.length ? <span>Numbered discs are the circuit&apos;s official corners.</span> : null}
        {note ? <span>{note}</span> : null}
      </div>
    </div>
  );
}

function formatSeconds(ms: number): string {
  const seconds = ms / 1000;
  return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)} ${seconds === 1 ? "second" : "seconds"}`;
}
