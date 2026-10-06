"use client";

import { useMemo, useState } from "react";

import { driverStyle, teamDriverStyles } from "@/lib/driver-style";
import { fitBounds, outlinePath, project, replayBounds, replayCars, type Viewport } from "@/lib/track-map";
import type { Driver } from "@/lib/published/types";
import type { PositionReplayFrame } from "@/types/domain";

// Drawn as plain SVG, not as a chart: the viewBox keeps one scale on both
// axes at any size on screen, which chart axes do not.
const VIEWPORT: Viewport = { width: 1000, height: 600, padding: 40 };
const MAP_BACKGROUND = "#0b0f17";

export function PositionReplay({ frames, drivers }: { frames: PositionReplayFrame[]; drivers: ReadonlyArray<Driver> }) {
  const [index, setIndex] = useState(0);
  // Taken from every frame, once. Moving through the replay changes which
  // cars are drawn, never where a point on the circuit lands.
  const projection = useMemo(() => {
    const bounds = replayBounds(frames);
    return bounds ? fitBounds(bounds, VIEWPORT) : null;
  }, [frames]);
  const outline = useMemo(() => (projection ? outlinePath(frames, projection) : ""), [frames, projection]);
  const styles = useMemo(() => teamDriverStyles(drivers), [drivers]);

  const frame = frames[index] || frames[0];
  if (!frame || !projection) {
    return <div className="text-sm text-slate-400">No replay frames available.</div>;
  }
  const cars = replayCars(frame);
  const unplaced = frame.positions.length - cars.length;
  return (
    <div className="space-y-4">
      <svg
        viewBox={`0 0 ${VIEWPORT.width} ${VIEWPORT.height}`}
        className="max-h-[70vh] w-full rounded border border-line"
        style={{ backgroundColor: MAP_BACKGROUND }}
        role="img"
        aria-label={`Car positions on the circuit, frame ${index + 1} of ${frames.length}`}
      >
        <path d={outline} fill="none" stroke="#263042" strokeWidth="6" strokeLinecap="round" />
        {cars.map((car) => {
          const at = project(projection, car);
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
          max={Math.max(frames.length - 1, 0)}
          value={index}
          onChange={(event) => setIndex(Number(event.target.value))}
        />
        <div className="w-24 text-right font-mono text-sm text-slate-400">
          {index + 1}/{frames.length}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
        <span>Lap <strong className="font-mono text-slate-300">{frame.lap_number ?? "--"}</strong></span>
        <span>Session time <strong className="font-mono text-slate-300">{frame.timestamp_ms != null ? `${(frame.timestamp_ms / 1000).toFixed(1)}s` : "--"}</strong></span>
        <span>Cars <strong className="font-mono text-slate-300">{cars.length}</strong></span>
        {unplaced > 0 ? <span>{unplaced} without a position in this frame</span> : null}
        <span>Team-mates share a colour: one marker is filled, the other hollow.</span>
      </div>
    </div>
  );
}
