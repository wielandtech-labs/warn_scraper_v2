import { useMemo, useRef, useState } from "react";

import { useNavigate } from "@tanstack/react-router";

import { fmtCompact, fmtNum } from "../lib/format";
import { DC_ANCHOR, US_MAP_VIEWBOX, US_STATE_PATHS } from "../lib/usStatePaths";

interface StateDatum {
  code: string;
  name: string;
  notice_count: number;
  layoff_total: number;
}

// slate-100 for zero, then sky-200/300/500/700 quartile buckets — sky-700 is
// the notices color used across the dashboard charts.
const BUCKET_COLORS = ["#f1f5f9", "#bae6fd", "#7dd3fc", "#0ea5e9", "#0369a1"];

function bucketOf(value: number, thresholds: number[]): number {
  if (value <= 0) return 0;
  for (let i = 0; i < thresholds.length; i++) {
    if (value <= thresholds[i]) return i + 1;
  }
  return thresholds.length + 1;
}

/** Clickable US choropleth shaded by layoff totals. The SVG is aria-hidden
 *  and mouse-only by design: the card grid rendered below it on /states is a
 *  complete accessible equivalent (the same 51 jurisdictions as real links
 *  with the same numbers), so 51 SVG tab stops would add nothing. */
export function UsChoroplethMap({ data }: { data: StateDatum[] }) {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ code: string; x: number; y: number } | null>(null);

  // Quartiles of the nonzero totals: the distribution is heavily skewed
  // toward a few large states, so fixed linear buckets would leave most of
  // the country in the lowest one.
  const thresholds = useMemo(() => {
    const nonzero = data
      .map((d) => d.layoff_total)
      .filter((v) => v > 0)
      .sort((a, b) => a - b);
    if (nonzero.length === 0) return [];
    return [0.25, 0.5, 0.75].map(
      (q) => nonzero[Math.min(nonzero.length - 1, Math.floor(q * nonzero.length))],
    );
  }, [data]);

  function go(code: string) {
    navigate({ to: "/states/$state", params: { state: code } });
  }

  function moveTo(code: string, e: { clientX: number; clientY: number }) {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setHover({ code, x: e.clientX - rect.left, y: e.clientY - rect.top });
  }

  const hovered = hover ? data.find((d) => d.code === hover.code) : undefined;
  const flip =
    hover && containerRef.current
      ? hover.x > containerRef.current.clientWidth * 0.7
      : false;
  const dc = data.find((d) => d.code === "DC");

  const legend = thresholds.length
    ? [
        { color: BUCKET_COLORS[0], label: "0" },
        { color: BUCKET_COLORS[1], label: `1–${fmtCompact(thresholds[0])}` },
        {
          color: BUCKET_COLORS[2],
          label: `${fmtCompact(thresholds[0])}–${fmtCompact(thresholds[1])}`,
        },
        {
          color: BUCKET_COLORS[3],
          label: `${fmtCompact(thresholds[1])}–${fmtCompact(thresholds[2])}`,
        },
        { color: BUCKET_COLORS[4], label: `> ${fmtCompact(thresholds[2])}` },
      ]
    : [{ color: BUCKET_COLORS[0], label: "0" }];

  return (
    <div ref={containerRef} className="card relative">
      <p className="sr-only">
        Map of layoffs by state. The state list below contains the same data as
        accessible links.
      </p>
      <svg
        viewBox={US_MAP_VIEWBOX}
        className="h-auto w-full"
        aria-hidden="true"
        focusable="false"
        onMouseMove={(e) => {
          if (hover) moveTo(hover.code, e);
        }}
        onMouseLeave={() => setHover(null)}
      >
        {data.map((s) => (
          <path
            key={s.code}
            d={US_STATE_PATHS[s.code]}
            fill={BUCKET_COLORS[bucketOf(s.layoff_total, thresholds)]}
            stroke="#fff"
            strokeWidth={1}
            strokeLinejoin="round"
            className="cursor-pointer"
            onClick={() => go(s.code)}
            onMouseEnter={(e) => moveTo(s.code, e)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
        {/* DC is too small to hit on a geographic map — callout square. */}
        {dc && (
          <g
            className="cursor-pointer"
            onClick={() => go("DC")}
            onMouseEnter={(e) => moveTo("DC", e)}
            onMouseLeave={() => setHover(null)}
          >
            <line
              x1={DC_ANCHOR.x}
              y1={DC_ANCHOR.y}
              x2={855}
              y2={258}
              stroke="#94a3b8"
              strokeWidth={1}
            />
            <rect
              x={855}
              y={250}
              width={20}
              height={20}
              rx={3}
              fill={BUCKET_COLORS[bucketOf(dc.layoff_total, thresholds)]}
              stroke="#94a3b8"
            />
            <text
              x={865}
              y={264}
              textAnchor="middle"
              fontSize={9}
              className="pointer-events-none select-none"
            >
              DC
            </text>
          </g>
        )}
        {/* Re-stroke the hovered state on top so neighbors don't overpaint it. */}
        {hover && (
          <path
            d={US_STATE_PATHS[hover.code]}
            fill="none"
            stroke="#0f172a"
            strokeWidth={1.5}
            strokeLinejoin="round"
            className="pointer-events-none"
          />
        )}
      </svg>

      {hover && hovered && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-md"
          style={{
            left: hover.x + (flip ? -12 : 12),
            top: hover.y + 12,
            transform: flip ? "translateX(-100%)" : undefined,
          }}
        >
          <div className="font-medium text-slate-900">{hovered.name}</div>
          <div className="text-slate-600">
            {fmtNum(hovered.notice_count)}{" "}
            {hovered.notice_count === 1 ? "notice" : "notices"}
          </div>
          <div className="text-slate-600">{fmtNum(hovered.layoff_total)} workers</div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
        <span className="font-medium text-slate-700">Workers affected</span>
        {legend.map((item, i) => (
          <span key={i} className="flex items-center gap-1.5">
            <span
              className="inline-block h-3 w-3 rounded-sm"
              style={{ backgroundColor: item.color }}
            />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}
