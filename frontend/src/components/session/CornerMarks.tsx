import type { PlacedCorner } from "@/lib/circuit-layout";

/**
 * The circuit's official corner numbers on a track map, each in a disc beside
 * the track with a short line to the corner it names. An SVG group, to be put
 * inside the map's own `<svg>` above the track and below anything that moves.
 */
export function CornerMarks({ corners, radius }: { corners: ReadonlyArray<PlacedCorner>; radius: number }) {
  if (corners.length === 0) {
    return null;
  }
  return (
    <g aria-label={`Corners ${corners[0].label} to ${corners[corners.length - 1].label}`}>
      {corners.map((corner) => (
        <g key={corner.label}>
          <title>Turn {corner.label}</title>
          <line x1={corner.at.x} y1={corner.at.y} x2={corner.labelAt.x} y2={corner.labelAt.y} stroke="#64748b" strokeWidth={Math.max(1, radius / 8)} />
          <circle cx={corner.labelAt.x} cy={corner.labelAt.y} r={radius} fill="#111722" stroke="#64748b" strokeWidth={Math.max(1, radius / 8)} />
          <text
            x={corner.labelAt.x}
            y={corner.labelAt.y}
            textAnchor="middle"
            dominantBaseline="central"
            // A lettered corner has three characters to fit in the same disc.
            fontSize={corner.label.length > 2 ? radius * 0.8 : radius}
            fontWeight="700"
            fill="#cbd5e1"
            className="font-mono"
          >
            {corner.label}
          </text>
        </g>
      ))}
    </g>
  );
}
