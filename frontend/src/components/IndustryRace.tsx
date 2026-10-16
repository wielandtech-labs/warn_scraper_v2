import type { IndustryTimeline } from "../api/client";
import type { ResolvedTheme } from "../hooks/useTheme";
import { fmtNum } from "../lib/format";
import { CHART_COLORS } from "../lib/themeColors";

/* Ranked-bar time-lapse of NAICS sectors for /timelapse: the TOP sectors by
   workers in the current frame, re-ranked every frame. Rows are absolutely
   positioned and slide with a CSS transform, keyed by sector, so a frame
   change is a style update rather than a chart re-layout (Recharts'
   own animations fight frame-by-frame data).

   One series (workers in WARN notices), so one hue — the layoffs red — with
   each bar named in text; no legend. Notices with no known industry are a
   separate grey "Unclassified" row under the race, never ranked with the
   sectors, so the share of the period the sectors explain stays visible. */

const TOP = 10;
const ROW = 34; // px per row, bar + label

export function IndustryRace({
  timeline,
  frame,
  theme,
  selected,
  onSelect,
  transitionMs,
}: {
  timeline: IndustryTimeline;
  /** Index into timeline.periods. */
  frame: number;
  theme: ResolvedTheme;
  /** Sector id the map is filtered to, if any. */
  selected: string | null;
  onSelect: (sector: string | null) => void;
  /** Slide/grow duration between frames; 0 for reduced motion. */
  transitionMs: number;
}) {
  const colors = CHART_COLORS[theme];
  const sectors = timeline.sectors.filter((s) => s.sector !== "unclassified");
  const unclassified = timeline.sectors.find((s) => s.sector === "unclassified");
  const ranked = [...sectors].sort(
    (a, b) => b.workers[frame] - a.workers[frame] || b.notices[frame] - a.notices[frame],
  );
  const rank = new Map(ranked.map((s, i) => [s.sector, i]));
  const shown = ranked.slice(0, TOP).filter((s) => s.notices[frame] > 0);
  // Per-frame scale: the race ranks within a period; the timeline above the
  // chart carries the magnitude from period to period.
  const max = Math.max(1, ...shown.map((s) => s.workers[frame]), unclassified?.workers[frame] ?? 0);

  const totalNotices = timeline.sectors.reduce((sum, s) => sum + s.notices[frame], 0);
  const knownNotices = totalNotices - (unclassified?.notices[frame] ?? 0);
  const knownPct = totalNotices > 0 ? Math.round((knownNotices / totalNotices) * 100) : null;

  const transition = transitionMs
    ? `transform ${transitionMs}ms ease-in-out, opacity ${transitionMs}ms ease-in-out`
    : "none";
  const grow = transitionMs ? `width ${transitionMs}ms ease-in-out` : "none";

  return (
    <div>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {knownPct === null
          ? "No notices this period."
          : `Industry known for ${knownPct}% of this period's notices. Tap a sector to map only its layoffs.`}
      </p>
      <ol
        className="relative mt-3"
        style={{ height: Math.max(1, shown.length) * ROW }}
        aria-label="Sectors ranked by workers affected this period"
      >
        {sectors.map((s) => {
          const r = rank.get(s.sector)!;
          const visible = r < TOP && s.notices[frame] > 0;
          const active = selected === s.sector;
          const dim = selected !== null && !active;
          return (
            <li
              key={s.sector}
              className="absolute inset-x-0 top-0"
              style={{
                transform: `translateY(${Math.min(r, TOP) * ROW}px)`,
                opacity: visible ? 1 : 0,
                // Parked off-list rows overlap what's below the list.
                pointerEvents: visible ? undefined : "none",
                transition,
                height: ROW,
              }}
              aria-hidden={!visible}
            >
              <button
                type="button"
                tabIndex={visible ? 0 : -1}
                aria-pressed={active}
                onClick={() => onSelect(active ? null : s.sector)}
                className="group flex h-full w-full flex-col justify-center rounded px-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-500"
              >
                <span className="flex items-baseline justify-between gap-2 text-xs leading-tight">
                  <span
                    className={`truncate ${
                      active
                        ? "font-semibold text-slate-900 dark:text-slate-50"
                        : "text-slate-700 group-hover:text-slate-900 dark:text-slate-300 dark:group-hover:text-slate-100"
                    }`}
                  >
                    {/* DOM order is NAICS order; the visual rank is a transform. */}
                    <span className="sr-only">{r + 1}. </span>
                    {s.name}
                  </span>
                  <span className="shrink-0 tabular-nums text-slate-500 dark:text-slate-400">
                    {fmtNum(s.workers[frame])}
                  </span>
                </span>
                <span className="mt-1 block h-2 w-full">
                  <span
                    className="block h-2 rounded-r"
                    style={{
                      width: `${(s.workers[frame] / max) * 100}%`,
                      minWidth: 2,
                      background: colors.layoffs,
                      opacity: dim ? 0.3 : 1,
                      transition: grow,
                    }}
                  />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {unclassified && (
        <div className="mt-2 border-t border-dashed border-slate-200 px-1 pt-2 dark:border-slate-800">
          <span className="flex items-baseline justify-between gap-2 text-xs">
            <span className="text-slate-500 dark:text-slate-400">Unclassified (industry unknown)</span>
            <span className="tabular-nums text-slate-500 dark:text-slate-400">
              {fmtNum(unclassified.workers[frame])}
            </span>
          </span>
          <span className="mt-1 block h-2 w-full">
            <span
              className="block h-2 rounded-r"
              style={{
                width: `${(unclassified.workers[frame] / max) * 100}%`,
                minWidth: 2,
                background: colors.axis,
                opacity: 0.6,
                transition: grow,
              }}
            />
          </span>
        </div>
      )}
      <details className="mt-3 text-xs">
        <summary className="cursor-pointer text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200">
          All sectors this period (table)
        </summary>
        <table className="mt-2 w-full tabular-nums">
          <thead className="text-left text-slate-500 dark:text-slate-400">
            <tr>
              <th className="py-1 font-medium">Sector</th>
              <th className="py-1 text-right font-medium">Notices</th>
              <th className="py-1 text-right font-medium">Workers</th>
            </tr>
          </thead>
          <tbody className="text-slate-700 dark:text-slate-300">
            {[...ranked, ...(unclassified ? [unclassified] : [])].map((s) => (
              <tr key={s.sector} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1 pr-2">{s.name}</td>
                <td className="py-1 text-right">{fmtNum(s.notices[frame])}</td>
                <td className="py-1 text-right">{fmtNum(s.workers[frame])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
