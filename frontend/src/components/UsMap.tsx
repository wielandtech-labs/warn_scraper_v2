import { type ReactNode, useRef, useState } from "react";

import { useNavigate } from "@tanstack/react-router";

import { useTheme } from "../hooks/useTheme";
import { US_MAP } from "../lib/themeColors";
import { DC_ANCHOR, US_MAP_VIEWBOX, US_STATE_PATHS } from "../lib/usStatePaths";

interface UsMapProps {
  /** Fill color per state code; states missing from the record get the
   *  theme's no-data fill. */
  fills: Record<string, string>;
  /** Tooltip card content for a hovered state; return null to suppress it. */
  tooltip: (code: string) => ReactNode;
  /** Legend row content, rendered under the map inside the card. */
  legend?: ReactNode;
  /** Screen-reader description of the map. */
  srLabel: string;
}

/** Clickable US map shaded per state; clicking a state navigates to its page.
 *  The SVG is aria-hidden and mouse-only by design: every page rendering it
 *  also renders a complete accessible equivalent (the same 51 jurisdictions
 *  as real links with the same data), so 51 SVG tab stops would add nothing —
 *  callers describe that equivalent in `srLabel`. */
export function UsMap({ fills, tooltip, legend, srLabel }: UsMapProps) {
  const navigate = useNavigate();
  const { resolved } = useTheme();
  const colors = US_MAP[resolved];
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ code: string; x: number; y: number } | null>(null);

  function go(code: string) {
    navigate({ to: "/states/$state", params: { state: code } });
  }

  // Single svg-level handler deriving the state from the event target's
  // data-code. Per-shape mouseEnter/Leave broke here: React 18 treats them as
  // continuous-priority (batched, not flushed between events), so the svg
  // mousemove handler's stale `hover` closure re-queued the OLD state code
  // after enter(new) in the same batch — the tooltip stuck on the first state.
  // The target is the browser's own hit test, so it can't go stale.
  function handleMove(e: { clientX: number; clientY: number; target: EventTarget }) {
    const code = (e.target as SVGElement).dataset?.code;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!code || !rect) {
      setHover(null);
      return;
    }
    setHover({ code, x: e.clientX - rect.left, y: e.clientY - rect.top });
  }

  const tooltipContent = hover ? tooltip(hover.code) : null;
  const flip =
    hover && containerRef.current
      ? hover.x > containerRef.current.clientWidth * 0.7
      : false;

  return (
    <div ref={containerRef} className="card relative">
      <p className="sr-only">{srLabel}</p>
      <svg
        viewBox={US_MAP_VIEWBOX}
        className="h-auto w-full"
        aria-hidden="true"
        focusable="false"
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
      >
        {Object.entries(US_STATE_PATHS).map(([code, d]) => (
          <path
            key={code}
            d={d}
            fill={fills[code] ?? colors.noData}
            stroke={colors.stateStroke}
            strokeWidth={1}
            strokeLinejoin="round"
            className="cursor-pointer"
            data-code={code}
            onClick={() => go(code)}
          />
        ))}
        {/* DC is too small to hit on a geographic map — callout square. */}
        <g className="cursor-pointer" onClick={() => go("DC")}>
          <line
            x1={DC_ANCHOR.x}
            y1={DC_ANCHOR.y}
            x2={855}
            y2={258}
            stroke={colors.connector}
            strokeWidth={1}
            data-code="DC"
          />
          <rect
            x={855}
            y={250}
            width={20}
            height={20}
            rx={3}
            fill={fills.DC ?? colors.noData}
            stroke={colors.connector}
            data-code="DC"
          />
          <text
            x={865}
            y={264}
            textAnchor="middle"
            fontSize={9}
            className="pointer-events-none select-none fill-slate-900 dark:fill-slate-100"
          >
            DC
          </text>
        </g>
        {/* Re-stroke the hovered state on top so neighbors don't overpaint it. */}
        {hover && (
          <path
            d={US_STATE_PATHS[hover.code]}
            fill="none"
            stroke={colors.hoverStroke}
            strokeWidth={1.5}
            strokeLinejoin="round"
            className="pointer-events-none"
          />
        )}
      </svg>

      {hover && tooltipContent && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-md dark:border-slate-700 dark:bg-slate-800"
          style={{
            left: hover.x + (flip ? -12 : 12),
            top: hover.y + 12,
            transform: flip ? "translateX(-100%)" : undefined,
          }}
        >
          {tooltipContent}
        </div>
      )}

      {legend && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
          {legend}
        </div>
      )}
    </div>
  );
}
