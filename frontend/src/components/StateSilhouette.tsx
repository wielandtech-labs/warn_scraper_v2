import { useMemo } from "react";

import { stateGeometry } from "../lib/stateGeometry";
import { US_STATE_PATHS } from "../lib/usStatePaths";

/* A state's outline as an inline SVG, cropped to its own bounds -- the same
   path data as the maps, so zero network cost. Decorative (aria-hidden): the
   state name always sits beside it. DC has no usable shape and renders as a
   small square. */
export function StateSilhouette({
  code,
  size = 40,
  className = "",
}: {
  code: string;
  size?: number;
  className?: string;
}) {
  const geo = useMemo(() => stateGeometry()[code], [code]);
  const d = US_STATE_PATHS[code];
  if (!geo || !d || code === "DC") {
    return (
      <svg width={size} height={size} viewBox="0 0 10 10" aria-hidden className={className}>
        <rect x="3" y="3" width="4" height="4" rx="1" fill="currentColor" />
      </svg>
    );
  }
  const { x, y, width, height } = geo.box;
  const pad = Math.max(width, height) * 0.06;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`${x - pad} ${y - pad} ${width + 2 * pad} ${height + 2 * pad}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden
      className={className}
    >
      <path d={d} fill="currentColor" />
    </svg>
  );
}
