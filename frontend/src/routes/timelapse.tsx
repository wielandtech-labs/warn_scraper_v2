import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";

import { api, type TimelineBucket } from "../api/client";
import { IndustryRace } from "../components/IndustryRace";
import { PageHeader } from "../components/PageHeader";
import { PlacesMap, type SelectedPlace } from "../components/PlacesMap";
import { QueryError } from "../components/QueryError";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import type { ResolvedTheme } from "../hooks/useTheme";
import { useTheme } from "../hooks/useTheme";
import { fmtDate, fmtNum } from "../lib/format";
import { EMPTY_PLACES } from "../lib/mapPlaces";
import { CHART_COLORS, HEAT_STOPS, US_MAP } from "../lib/themeColors";
import {
  currentPeriod,
  framesGeoJSON,
  heatScaleMax,
  periodLabel,
  periodOf,
  periodStartMonth,
  statesReporting,
} from "../lib/timelapse";
import { US_MAP_VIEWBOX, US_STATE_PATHS } from "../lib/usStatePaths";

/* /timelapse — where and in which industries layoffs happen, period by
   period. Both payloads (per-place cells for the map, per-sector series for
   the race) load once per bucket/window; playing only moves an index, so no
   frame costs a request.

   Coverage is the trap: states' archives start in different years, so an
   early frame looks quiet partly because fewer states report. The toolbar
   counts the states reporting in each frame and maps the ones that aren't. */

const DEFAULT_SINCE = 2015;
// Window starts offered. 1999 is the earliest any state's backfill reaches (IL).
const WINDOWS = [
  [2015, "Since 2015"],
  [2010, "Since 2010"],
  [1999, "Since 1999"],
] as const;
const BUCKETS: [TimelineBucket, string][] = [
  ["year", "Year"],
  ["quarter", "Quarter"],
  ["month", "Month"],
];
// Base time per frame at 1x; finer buckets have more frames, so move faster.
const FRAME_MS: Record<TimelineBucket, number> = { year: 1400, quarter: 800, month: 300 };
const SPEEDS = [0.5, 1, 2] as const;

function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

export function TimelapsePage() {
  useDocumentTitle("Layoffs over time — WARN Index");
  const { resolved } = useTheme();
  const navigate = useNavigate({ from: "/timelapse" });
  const search = useSearch({ from: "/timelapse" });
  const bucket: TimelineBucket = search.bucket ?? "quarter";
  const since = search.since ?? DEFAULT_SINCE;
  const after = `${since}-01-01`;
  const industry = search.industry ?? null;
  const reducedMotion = useReducedMotion();

  // The frame is a period key, not an index, so it survives a bucket or
  // window change (re-keyed to the period holding the same month).
  const [at, setAt] = useState<string | null>(search.at ?? null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [selected, setSelected] = useState<SelectedPlace | null>(null);

  const industryQuery = useQuery({
    queryKey: ["timelapse", "industries", bucket, after],
    queryFn: () => api.statsIndustriesTimeline({ bucket, after }),
  });
  const placesQuery = useQuery({
    queryKey: ["timelapse", "places", bucket, after, industry],
    queryFn: () => api.mapPlacesTimeline({ bucket, after, industry: industry ?? undefined }),
    // Old frames stay up while a sector filter loads — but not across a
    // bucket or window change, whose period keys wouldn't match the frames.
    placeholderData: (prev, prevQuery) =>
      prevQuery?.queryKey[2] === bucket && prevQuery?.queryKey[3] === after ? prev : undefined,
  });
  const statusQuery = useQuery({
    queryKey: ["scraper-runs", "status"],
    queryFn: () => api.listScraperStatus(),
  });

  const timeline = industryQuery.data;
  // A stray future-dated notice would add empty frames past today.
  const now = currentPeriod(bucket);
  const frames = useMemo(
    () => (timeline ? timeline.periods.filter((p) => p <= now) : []),
    [timeline, now],
  );
  const last = frames.length - 1;
  const partial = frames[last] === now;
  // With no frame chosen yet: the start (autoplay), or with reduced motion
  // the last complete period.
  const startIdx = reducedMotion ? (partial && last > 0 ? last - 1 : last) : 0;
  const idx = at !== null && frames.includes(at) ? frames.indexOf(at) : at === null ? startIdx : 0;
  const period = frames[idx];

  const mapFrames = useMemo(
    () => (placesQuery.data ? framesGeoJSON(placesQuery.data, frames) : null),
    [placesQuery.data, frames],
  );
  const heatMax = useMemo(
    () => (placesQuery.data ? heatScaleMax(placesQuery.data) : undefined),
    [placesQuery.data],
  );

  // National totals per frame, from the race payload (all notices, including
  // those with no industry or no geocode).
  const totals = useMemo(
    () =>
      frames.map((_, i) =>
        (timeline?.sectors ?? []).reduce(
          (acc, s) => ({ notices: acc.notices + s.notices[i], workers: acc.workers + s.workers[i] }),
          { notices: 0, workers: 0 },
        ),
      ),
    [frames, timeline],
  );

  // First visit with no frame in the URL: play from the start, unless the
  // reader asked for less motion — then rest on the last complete period.
  useEffect(() => {
    if (at !== null || frames.length === 0) return;
    setAt(frames[startIdx]);
    if (!reducedMotion) setPlaying(true);
    // Once per page visit, when the frames first arrive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frames.length > 0]);

  // Playback: one timer per frame, so a pause or a scrub cancels cleanly.
  useEffect(() => {
    if (!playing || frames.length === 0) return;
    if (idx >= last) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setAt(frames[idx + 1]), FRAME_MS[bucket] / speed);
    return () => clearTimeout(t);
  }, [playing, idx, last, frames, bucket, speed]);

  // The URL follows the frame only while paused: a navigate per tick would
  // re-render the route and flood history-replace calls.
  useEffect(() => {
    if (playing || at === null || at === search.at) return;
    navigate({ search: (prev) => ({ ...prev, at }), replace: true, resetScroll: false });
  }, [playing, at, search.at, navigate]);

  const reporting = useMemo(
    () => (statusQuery.data && period ? statesReporting(statusQuery.data, period) : null),
    [statusQuery.data, period],
  );
  const covered = statusQuery.data?.length ?? 0;

  const togglePlay = () => {
    if (playing) return setPlaying(false);
    if (idx >= last) setAt(frames[0]); // replay from the start
    setPlaying(true);
  };
  const setBucket = (b: TimelineBucket) => {
    const next = period ? periodOf(periodStartMonth(period), b) : null;
    setAt(next);
    navigate({
      search: (prev) => ({ ...prev, bucket: b === "quarter" ? undefined : b, at: next ?? undefined }),
      replace: true,
      resetScroll: false,
    });
  };
  const setSince = (y: number) =>
    navigate({
      search: (prev) => ({ ...prev, since: y === DEFAULT_SINCE ? undefined : y }),
      replace: true,
      resetScroll: false,
    });
  const setIndustry = (sector: string | null) =>
    navigate({
      search: (prev) => ({ ...prev, industry: sector ?? undefined }),
      replace: true,
      resetScroll: false,
    });

  const frameData = mapFrames?.[idx] ?? EMPTY_PLACES;
  // The selected place's counts in the current frame (zero if it had none).
  const selectedHere = useMemo(
    () =>
      selected
        ? frameData.features.find(
            (f) => f.properties.lat === selected.lat && f.properties.lon === selected.lon,
          )?.properties ?? { ...selected, n: 0, w: 0 }
        : null,
    [selected, frameData],
  );
  const industryName = industry
    ? timeline?.sectors.find((s) => s.sector === industry)?.name ?? industry
    : null;

  const total = totals[idx];
  const label = period ? periodLabel(period) : "";
  const isPartial = partial && idx === last;
  const valueText = period
    ? `${label}${isPartial ? " (partial)" : ""}: ${fmtNum(total.notices)} notices, ${fmtNum(
        total.workers,
      )} workers${reporting ? `; ${reporting.size} of ${covered} states reporting` : ""}`
    : "";

  if (industryQuery.isError) return <QueryError onRetry={() => industryQuery.refetch()} />;

  return (
    <div className="space-y-4">
      <PageHeader
        kicker="Explore"
        title="Layoffs over time"
        lede="Where WARN layoffs happen, and in which industries, period by period. Press play, or drag the timeline."
        aside={
          <Link to="/map" className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
            Explore the full map →
          </Link>
        }
      />

      <section
        aria-label="Timeline"
        className="space-y-3 rounded-xl border border-slate-200 bg-white p-3 sm:p-4 dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <button
            type="button"
            onClick={togglePlay}
            disabled={frames.length < 2}
            aria-label={playing ? "Pause" : "Play"}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900"
          >
            {playing ? (
              <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true" fill="currentColor">
                <rect x="3" y="2" width="3.5" height="12" rx="1" />
                <rect x="9.5" y="2" width="3.5" height="12" rx="1" />
              </svg>
            ) : (
              <svg viewBox="0 0 16 16" className="ml-0.5 h-4 w-4" aria-hidden="true" fill="currentColor">
                <path d="M4 2.5v11a.75.75 0 0 0 1.14.64l9-5.5a.75.75 0 0 0 0-1.28l-9-5.5A.75.75 0 0 0 4 2.5Z" />
              </svg>
            )}
          </button>
          <div className="min-w-0">
            <p className="text-xl font-semibold tabular-nums leading-tight text-slate-900 dark:text-slate-50">
              {label || "…"}
              {isPartial && (
                <span className="ml-2 align-middle text-xs font-medium text-slate-500 dark:text-slate-400">
                  partial, through {fmtDate(new Date().toISOString().slice(0, 10))}
                </span>
              )}
            </p>
            <p className="text-sm tabular-nums text-slate-600 dark:text-slate-400">
              {total ? `${fmtNum(total.workers)} workers · ${fmtNum(total.notices)} notices` : "Loading…"}
            </p>
          </div>
          {reporting && (
            <div className="ml-auto flex items-center gap-2">
              <CoverageInset reporting={reporting} theme={resolved} />
              <p className="text-sm leading-tight text-slate-700 dark:text-slate-300">
                <span className="font-semibold tabular-nums">
                  {reporting.size} of {covered}
                </span>{" "}
                states
                <br />
                <span className="text-xs text-slate-500 dark:text-slate-400">reporting yet</span>
              </p>
            </div>
          )}
        </div>

        <div>
          <FrameBars totals={totals} idx={idx} partial={partial} theme={resolved} />
          <input
            type="range"
            min={0}
            max={Math.max(0, last)}
            step={1}
            value={idx}
            disabled={frames.length === 0}
            onChange={(e) => {
              setPlaying(false);
              setAt(frames[Number(e.target.value)]);
            }}
            aria-label="Period"
            aria-valuetext={valueText}
            className="block w-full accent-brand"
          />
          <div className="flex justify-between text-xs tabular-nums text-slate-500 dark:text-slate-400">
            <span>{frames[0] ? periodLabel(frames[0]) : ""}</span>
            <span>{frames[last] ? periodLabel(frames[last]) : ""}</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <Segmented
            label="Time step"
            options={BUCKETS}
            value={bucket}
            onChange={setBucket}
          />
          <Segmented
            label="Window"
            options={WINDOWS.map(([y, l]) => [y, l] as [number, string])}
            value={since}
            onChange={setSince}
          />
          <Segmented
            label="Speed"
            options={SPEEDS.map((s) => [s, `${s}×`] as [(typeof SPEEDS)[number], string])}
            value={speed}
            onChange={setSpeed}
          />
        </div>
        {/* Spoken once the frame settles; silent while playing. */}
        <p className="sr-only" aria-live={playing ? "off" : "polite"}>
          {valueText}
        </p>
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <section aria-label="Map of layoffs in this period" className="space-y-2">
          {industryName && (
            <button
              type="button"
              onClick={() => setIndustry(null)}
              className="rounded-full bg-slate-900 px-3 py-1 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
            >
              Map: {industryName} only <span aria-hidden="true">✕</span>
              <span className="sr-only">(show all industries)</span>
            </button>
          )}
          <div className="relative overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
            <PlacesMap
              data={frameData}
              mode="heat"
              theme={resolved}
              initial={null}
              selected={selectedHere}
              heatMax={heatMax}
              onViewChange={() => {}}
              onSelect={setSelected}
              className="h-[50svh] w-full bg-slate-100 md:h-[60vh] dark:bg-slate-900"
            />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-3 rounded-lg bg-white/90 px-2.5 py-1 text-base font-semibold tabular-nums text-slate-900 shadow dark:bg-slate-900/90 dark:text-slate-50"
            >
              {label}
              {isPartial && <span className="ml-1 text-xs font-medium text-slate-500">partial</span>}
            </div>
            <HeatLegend max={heatMax} />
            {placesQuery.isFetching && (
              <div className="pointer-events-none absolute bottom-14 left-3 rounded-full bg-white/90 px-2.5 py-1 text-xs text-slate-600 shadow dark:bg-slate-900/90 dark:text-slate-300">
                Loading…
              </div>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {selectedHere
              ? `${selectedHere.label}, ${label}: ${fmtNum(selectedHere.n)} notices · ${fmtNum(selectedHere.w)} workers.`
              : "Geocoded notices only, by filing date. Zoom in and tap a place for its numbers."}
          </p>
        </section>

        <section
          aria-labelledby="race-title"
          className="rounded-xl border border-slate-200 bg-white p-3 sm:p-4 dark:border-slate-800 dark:bg-slate-900"
        >
          <h2 id="race-title" className="text-base font-semibold text-slate-900 dark:text-slate-50">
            Workers affected by industry, {label}
          </h2>
          {timeline && period ? (
            <IndustryRace
              timeline={timeline}
              frame={idx}
              theme={resolved}
              selected={industry}
              onSelect={setIndustry}
              transitionMs={reducedMotion ? 0 : Math.min(500, (FRAME_MS[bucket] / speed) * 0.8)}
            />
          ) : (
            <p className="mt-2 text-sm text-slate-500">Loading…</p>
          )}
        </section>
      </div>
    </div>
  );
}

function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: [T, string][];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <div
        role="group"
        aria-label={label}
        className="inline-flex rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900"
      >
        {options.map(([v, l]) => (
          <button
            key={String(v)}
            type="button"
            aria-pressed={value === v}
            onClick={() => onChange(v)}
            className={`rounded-full px-2.5 py-0.5 font-medium transition-colors ${
              value === v
                ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
            }`}
          >
            {l}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Workers per frame as thin columns above the scrubber, the current frame
 *  in red: where this frame sits in the whole curve. Decorative — the
 *  scrubber's value text and the header state the numbers. */
function FrameBars({
  totals,
  idx,
  partial,
  theme,
}: {
  totals: { workers: number }[];
  idx: number;
  partial: boolean;
  theme: ResolvedTheme;
}) {
  const colors = CHART_COLORS[theme];
  const n = totals.length;
  const max = Math.max(1, ...totals.map((t) => t.workers));
  const H = 40;
  return (
    <svg viewBox={`0 0 ${Math.max(1, n)} ${H}`} preserveAspectRatio="none" className="block h-10 w-full" aria-hidden="true">
      {totals.map((t, i) => {
        const h = Math.max(0.5, (t.workers / max) * H);
        const isPartial = partial && i === n - 1;
        return (
          <rect
            key={i}
            x={i + 0.1}
            width={0.8}
            y={H - h}
            height={h}
            fill={i === idx ? colors.layoffs : colors.axis}
            opacity={i === idx ? 1 : isPartial ? 0.2 : 0.35}
          />
        );
      })}
    </svg>
  );
}

/** Small US map: states with notices on record by this period filled, the
 *  rest hatched as "no data yet". Decorative; the count beside it, and the
 *  scrubber's value text, say the same thing in words. */
function CoverageInset({ reporting, theme }: { reporting: Set<string>; theme: ResolvedTheme }) {
  const c = US_MAP[theme];
  const on = theme === "dark" ? "#6e6c66" : "#a3a199";
  return (
    <svg viewBox={US_MAP_VIEWBOX} className="h-9 w-14 shrink-0" aria-hidden="true">
      <defs>
        <pattern id="tl-hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="10" height="10" fill={c.noData} />
          <line x1="0" y1="0" x2="0" y2="10" stroke={on} strokeWidth="3" opacity="0.6" />
        </pattern>
      </defs>
      {Object.entries(US_STATE_PATHS).map(([code, d]) => (
        <path
          key={code}
          d={d}
          fill={reporting.has(code) ? on : "url(#tl-hatch)"}
          stroke={c.stateStroke}
          strokeWidth={1}
        />
      ))}
    </svg>
  );
}

/** The heat ramp with its fixed scale: the same color means the same density
 *  of workers in every frame. */
function HeatLegend({ max }: { max: number | undefined }) {
  const gradient = `linear-gradient(to right, ${HEAT_STOPS.map(([s, c]) => `${c} ${s * 100}%`).join(", ")})`;
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute bottom-7 left-3 w-40 rounded-lg bg-white/90 px-2 py-1.5 text-[0.65rem] leading-tight text-slate-600 shadow dark:bg-slate-900/90 dark:text-slate-300"
    >
      <div className="h-2 rounded-full" style={{ background: gradient }} />
      <div className="mt-1 flex justify-between">
        <span>fewer</span>
        <span>more workers</span>
      </div>
      <div className="text-slate-500 dark:text-slate-400">
        Same scale every period{max ? `; one place counts in full from ${fmtNum(max)} workers` : ""}
      </div>
    </div>
  );
}
