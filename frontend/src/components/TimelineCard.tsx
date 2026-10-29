import type { TimelineBucket } from "../api/client";
import type { ResolvedTheme } from "../hooks/useTheme";
import { fmtDate, fmtNum } from "../lib/format";
import { periodLabel, WINDOWS } from "../lib/timelapse";
import { CHART_COLORS, US_MAP } from "../lib/themeColors";
import { US_MAP_VIEWBOX, US_STATE_PATHS } from "../lib/usStatePaths";

/* /map's one time control: play/pause, a scrubber over the periods with
   each period's workers drawn above it, and the step/range/speed choices.
   "Show" switches between one period at a time and all time combined (the
   aggregate map); scrubbing or playing also picks a period. The page hides
   the filter bar's date picker, so time is only ever set here.

   Coverage is the trap: states' archives start in different years, so an
   early frame looks quiet partly because fewer states report. The card counts
   the states reporting in each frame and maps the ones that aren't. */

const BUCKETS: [TimelineBucket, string][] = [
  ["year", "Year"],
  ["quarter", "Quarter"],
  ["month", "Month"],
];
export const SPEEDS = [0.5, 1, 2] as const;
export type Speed = (typeof SPEEDS)[number];

export function TimelineCard({
  frames,
  idx,
  partial,
  totals,
  reporting,
  covered,
  theme,
  playing,
  onTogglePlay,
  onScrub,
  onShowAllTime,
  dateLimit,
  bucket,
  onBucket,
  since,
  onSince,
  speed,
  onSpeed,
}: {
  frames: string[];
  /** Index into frames; -1 while the map shows all time. */
  idx: number;
  /** The last frame is the period today falls in. */
  partial: boolean;
  /** National notices/workers per frame (every notice, geocoded or not). */
  totals: { notices: number; workers: number }[];
  reporting: Set<string> | null;
  covered: number;
  theme: ResolvedTheme;
  playing: boolean;
  onTogglePlay: () => void;
  onScrub: (i: number) => void;
  onShowAllTime: (allTime: boolean) => void;
  /** A date filter narrowing the timeline (from an older link), shown with
   *  a way to remove it. */
  dateLimit: { text: string; onClear: () => void } | null;
  bucket: TimelineBucket;
  onBucket: (b: TimelineBucket) => void;
  since: number;
  onSince: (y: number) => void;
  speed: Speed;
  onSpeed: (s: Speed) => void;
}) {
  const allTime = idx < 0;
  const last = frames.length - 1;
  const period = allTime ? undefined : frames[idx];
  const total = allTime ? undefined : totals[idx];
  const label = period ? periodLabel(period) : "";
  const isPartial = partial && idx === last;
  const valueText = allTime
    ? "All time"
    : period && total
      ? `${label}${isPartial ? " (partial)" : ""}: ${fmtNum(total.notices)} notices, ${fmtNum(
          total.workers,
        )} workers${reporting ? `; ${reporting.size} of ${covered} states reporting` : ""}`
      : "";

  return (
    <section
      aria-label="Timeline"
      className="space-y-3 rounded-xl border border-slate-200 bg-white p-3 sm:p-4 dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button
          type="button"
          onClick={onTogglePlay}
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
            {allTime ? "All time" : label || "…"}
            {isPartial && (
              <span className="ml-2 align-middle text-xs font-medium text-slate-500 dark:text-slate-400">
                partial, through {fmtDate(new Date().toISOString().slice(0, 10))}
              </span>
            )}
          </p>
          <p className="text-sm tabular-nums text-slate-600 dark:text-slate-400">
            {allTime
              ? "Every notice on record, combined. Press play or drag the timeline to see one period at a time."
              : total
                ? `${fmtNum(total.workers)} workers · ${fmtNum(total.notices)} notices`
                : "Loading…"}
          </p>
        </div>
        {!allTime && reporting && (
          <div className="ml-auto flex items-center gap-2">
            <CoverageInset reporting={reporting} theme={theme} />
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
        <FrameBars totals={totals} idx={idx} partial={partial} theme={theme} />
        <input
          type="range"
          min={0}
          max={Math.max(0, last)}
          step={1}
          value={allTime ? Math.max(0, last) : idx}
          disabled={frames.length === 0}
          onChange={(e) => onScrub(Number(e.target.value))}
          aria-label="Period"
          aria-valuetext={valueText}
          className={`block w-full accent-brand ${allTime ? "opacity-50" : ""}`}
        />
        <div className="flex justify-between text-xs tabular-nums text-slate-500 dark:text-slate-400">
          <span>{frames[0] ? periodLabel(frames[0]) : ""}</span>
          <span>{frames[last] ? periodLabel(frames[last]) : ""}</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <Segmented
          label="Show"
          options={[
            [false, "One period"],
            [true, "All time"],
          ]}
          value={allTime}
          onChange={onShowAllTime}
        />
        <Segmented label="Step" options={BUCKETS} value={bucket} onChange={onBucket} />
        <Segmented
          label="Range"
          options={WINDOWS.map(([y, l]) => [y, l] as [number, string])}
          value={since}
          onChange={onSince}
        />
        <Segmented
          label="Speed"
          options={SPEEDS.map((s) => [s, `${s}×`] as [Speed, string])}
          value={speed}
          onChange={onSpeed}
        />
      </div>
      {dateLimit && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Dates limited to {dateLimit.text}.{" "}
          <button
            type="button"
            onClick={dateLimit.onClear}
            className="font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            Remove limit
          </button>
        </p>
      )}
      {/* Spoken once the frame settles; silent while playing. */}
      <p className="sr-only" aria-live={playing ? "off" : "polite"}>
        {valueText}
      </p>
    </section>
  );
}

function Segmented<T extends string | number | boolean>({
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
