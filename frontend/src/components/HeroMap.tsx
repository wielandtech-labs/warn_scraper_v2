import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";

import { api } from "../api/client";
import type { StateStat } from "../api/types";
import { useTheme } from "../hooks/useTheme";
import { fmtNum, stateName } from "../lib/format";
import { stateGeometry } from "../lib/stateGeometry";
import { CHART_COLORS, US_MAP } from "../lib/themeColors";
import { DC_ANCHOR, US_MAP_VIEWBOX, US_STATE_PATHS } from "../lib/usStatePaths";
import { NO_COUNTS } from "../lib/unavailable";
import { Sparkline } from "./Sparkline";
import { StateSilhouette } from "./StateSilhouette";
import type { Bucket } from "./TimeRangeToggle";

/* The dashboard hero: a dot map of where layoffs landed in the selected
   range, with a floating panel over it that answers "and what does that
   look like over time?" for the nation or the state under the pointer.

   Data art, not decoration -- each dot's AREA is proportional to workers
   affected, and the biggest few pulse. Everything is inline SVG from the
   path data the other maps already ship: no image requests, no map library.
   The SVG is aria-hidden; the panel (and the page's state links) carry the
   numbers for assistive tech. */

const MAX_R = 26; // viewBox units, for the largest state
const PULSING = 6; // only the top few animate: cheap, and draws the eye

interface Props {
  byState: StateStat[] | undefined;
  bucket: Bucket;
  after?: string;
  rangeLabel: string;
  /** National layoff series for the default panel, oldest first. */
  national: (number | null)[];
  /** byState failed: show dashes instead of loading placeholders. */
  failed?: boolean;
  controls?: ReactNode;
}

export function HeroMap({ byState, bucket, after, rangeLabel, national, failed = false, controls }: Props) {
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];
  const mapColors = US_MAP[resolved];
  const navigate = useNavigate();
  const geo = useMemo(() => stateGeometry(), []);

  // The last state pointed at, kept after the pointer leaves the map: the
  // panel overlaps the map, so clearing on leave would make its "Open state"
  // link unreachable. A button in the panel returns to the US view.
  const [target, setTarget] = useState<string | null>(null);
  // Hover intent: a pointer sweeping across the map shouldn't fire a fetch
  // for every state it crosses.
  const [focusCode, setFocusCode] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setFocusCode(target), target ? 150 : 0);
    return () => clearTimeout(t);
  }, [target]);

  const stats = useMemo(() => new Map((byState ?? []).map((s) => [s.state, s])), [byState]);
  const totalLayoffs = byState?.reduce((a, s) => a + s.layoff_total, 0) ?? null;
  const totalNotices = byState?.reduce((a, s) => a + s.notice_count, 0) ?? null;

  const dots = useMemo(() => {
    const rows = (byState ?? []).filter((s) => s.layoff_total > 0 && geo[s.state]);
    const max = Math.max(1, ...rows.map((s) => s.layoff_total));
    const ranked = rows.slice().sort((a, b) => b.layoff_total - a.layoff_total);
    const pulsing = new Set(ranked.slice(0, PULSING).map((s) => s.state));
    // Draw small over big so every dot stays hoverable.
    return ranked.reverse().map((s) => ({
      code: s.state,
      ...geo[s.state].anchor,
      r: Math.max(2.5, Math.sqrt(s.layoff_total / max) * MAX_R),
      pulse: pulsing.has(s.state),
    }));
  }, [byState, geo]);

  const stateSeries = useQuery({
    queryKey: ["stats", "over-time", { state: focusCode, after, bucket }],
    queryFn: () => api.statsOverTime({ state: focusCode!, after, bucket }),
    enabled: !!focusCode,
  });

  function codeFrom(e: { target: EventTarget }): string | null {
    return (e.target as SVGElement).dataset?.code ?? null;
  }

  const panelCode = focusCode;
  const panelStat = panelCode ? stats.get(panelCode) : null;
  const panelSeries = panelCode
    ? (stateSeries.data ?? []).map((r) => (r.projected_notice_count != null ? null : r.layoff_total))
    : national;

  return (
    <section className="relative overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-slate-100 dark:border-slate-800 dark:from-slate-900 dark:via-slate-950 dark:to-slate-950">
      <div className="grid gap-6 p-5 sm:p-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,8fr)] lg:items-center">
        <div className="relative z-10 space-y-5">
          <div>
            <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-brand">
              WARN Layoff Tracker · {rangeLabel}
            </p>
            <h1 className="mt-2 text-3xl font-semibold leading-tight text-slate-900 sm:text-4xl dark:text-slate-50">
              US WARN Layoff Tracker &amp; Database
            </h1>
            <p className="mt-2 max-w-md text-sm text-slate-600 dark:text-slate-400">
              Track Worker Adjustment and Retraining Notification (WARN) filings, plant closures, and workforce reductions across all 50 states, updated daily.
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
            <Figure label="Workers affected" value={totalLayoffs} failed={failed} lead />
            <Figure label="Notices" value={totalNotices} failed={failed} />
            <Figure label="States reporting" value={byState ? byState.length : null} failed={failed} />
          </dl>
          {controls}
        </div>

        {/* Bottom/right gutter on wide screens: the panel floats there,
            over ocean, instead of over Florida. */}
        <div className="relative sm:pb-16 lg:pb-20 lg:pr-10">
          <svg
            viewBox={US_MAP_VIEWBOX}
            className="h-auto w-full"
            aria-hidden="true"
            focusable="false"
            onMouseMove={(e) => {
              const code = codeFrom(e);
              if (code) setTarget(code);
            }}
            onPointerUp={(e) => {
              const code = codeFrom(e);
              if (!code) return;
              // Touch has no hover: first tap selects (panel shows it, with a
              // link); mouse clicks go straight to the state page.
              if (e.pointerType === "touch" && target !== code) setTarget(code);
              else navigate({ to: "/states/$state", params: { state: code } });
            }}
          >
            {Object.entries(US_STATE_PATHS).map(([code, d]) => (
              <path
                key={code}
                d={d}
                data-code={code}
                fill={code === target ? mapColors.hoverFill : mapColors.noData}
                stroke={mapColors.stateStroke}
                strokeWidth={1}
                strokeLinejoin="round"
                className="cursor-pointer transition-[fill] duration-150"
              />
            ))}
            <rect x={DC_ANCHOR.x - 4} y={DC_ANCHOR.y - 4} width={8} height={8} fill="transparent" data-code="DC" />
            {dots.map((dot) => (
              <g key={dot.code} className="cursor-pointer">
                {dot.pulse && (
                  <circle
                    cx={dot.x}
                    cy={dot.y}
                    r={dot.r}
                    fill="none"
                    stroke={chart.layoffs}
                    className="hero-pulse pointer-events-none"
                  />
                )}
                <circle
                  cx={dot.x}
                  cy={dot.y}
                  r={dot.r}
                  data-code={dot.code}
                  fill={chart.layoffs}
                  fillOpacity={dot.code === target ? 0.6 : 0.32}
                  stroke={chart.layoffs}
                  strokeWidth={1.25}
                />
              </g>
            ))}
          </svg>

          {/* The overlay: a glass panel floating over the map's empty
              south-east corner (static below the map on small screens). */}
          <div
            className="mt-3 w-full rounded-xl border border-slate-200/80 bg-white/80 p-4 shadow-lg backdrop-blur-sm sm:absolute sm:bottom-0 sm:right-0 sm:mt-0 sm:w-60 dark:border-slate-700/70 dark:bg-slate-900/80"
          >
            <div className="flex items-center gap-3">
              {panelCode ? (
                <StateSilhouette code={panelCode} size={36} className="text-slate-400 dark:text-slate-500" />
              ) : null}
              <div className="min-w-0 flex-1">
                <div className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
                  {panelCode ? rangeLabel : `United States · ${rangeLabel}`}
                </div>
                <div className="truncate font-display text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {panelCode ? stateName(panelCode) : "Workers affected"}
                </div>
              </div>
              {target && (
                <button
                  type="button"
                  onClick={() => setTarget(null)}
                  aria-label="Back to the national view"
                  className="self-start rounded-full px-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                >
                  ×
                </button>
              )}
            </div>
            <div className="mt-2 flex items-baseline gap-3 text-sm tabular-nums">
              <span className="font-display text-2xl font-semibold text-slate-900 dark:text-slate-50">
                {panelCode
                  ? panelCode in NO_COUNTS
                    ? "—"
                    : fmtNum(panelStat?.layoff_total ?? 0)
                  : fmtNum(totalLayoffs)}
              </span>
              <span className="text-slate-500 dark:text-slate-400">
                {fmtNum(panelCode ? (panelStat?.notice_count ?? 0) : totalNotices)} notices
              </span>
            </div>
            <Sparkline
              values={panelSeries}
              color={chart.layoffs}
              height={44}
              className={`mt-2 transition-opacity ${panelCode && stateSeries.isFetching ? "opacity-40" : ""}`}
            />
            <div className="mt-1 text-[0.7rem] text-slate-500 dark:text-slate-400">
              {panelCode ? (
                <Link
                  to="/states/$state"
                  params={{ state: panelCode }}
                  className="font-medium text-sky-700 hover:underline dark:text-sky-400"
                >
                  Open {stateName(panelCode)} →
                </Link>
              ) : (
                "Hover a state for its trend · dot area = workers affected"
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Figure({
  label,
  value,
  failed = false,
  lead = false,
}: {
  label: string;
  value: number | null;
  failed?: boolean;
  lead?: boolean;
}) {
  return (
    <div className={lead ? "col-span-2" : ""}>
      <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
        {label}
      </dt>
      <dd
        className={`mt-1 font-display font-semibold tabular-nums text-slate-900 dark:text-slate-50 ${lead ? "text-4xl sm:text-5xl" : "text-2xl"}`}
      >
        {value == null && failed ? (
          "—"
        ) : value == null ? (
          <span className="inline-block h-7 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
        ) : (
          fmtNum(value)
        )}
      </dd>
    </div>
  );
}
