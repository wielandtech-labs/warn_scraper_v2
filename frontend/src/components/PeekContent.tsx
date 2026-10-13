import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { useTheme } from "../hooks/useTheme";
import { fmtDate, fmtNum, stateName } from "../lib/format";
import { CHART_COLORS } from "../lib/themeColors";
import { NO_COUNTS } from "../lib/unavailable";
import { CompanyLogo } from "./CompanyLogo";
import { Sparkline } from "./Sparkline";
import { StateSilhouette } from "./StateSilhouette";

/* Bodies for <Peek>: a state's or a company's all-time WARN history at a
   glance. The state peek reuses the state page's all-time query keys, so a
   peek warms the cache for the click that often follows it. */

const KICKER =
  "text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400";

export function StatePeek({ code }: { code: string }) {
  const { resolved } = useTheme();
  const byState = useQuery({
    queryKey: ["stats", "by-state"],
    queryFn: () => api.statsByState(),
  });
  const series = useQuery({
    queryKey: ["stats", "over-time", { state: code, after: undefined, bucket: "year" }],
    queryFn: () => api.statsOverTime({ state: code, bucket: "year" }),
  });
  const row = byState.data?.find((s) => s.state === code);
  const years = series.data ?? [];
  return (
    <>
      <div className="flex items-center gap-3">
        <StateSilhouette code={code} size={32} className="text-slate-400 dark:text-slate-500" />
        <div>
          <div className={KICKER}>All time</div>
          <div className="font-display text-base font-semibold">{stateName(code)}</div>
        </div>
      </div>
      <Figures
        workers={code in NO_COUNTS ? null : (row?.layoff_total ?? null)}
        notices={row?.notice_count ?? null}
      />
      <Sparkline
        values={years.map((r) => (r.projected_notice_count != null ? null : r.layoff_total))}
        color={CHART_COLORS[resolved].layoffs}
        className="mt-2"
      />
      {years.length > 1 && (
        <div className="mt-1 text-[0.7rem] text-slate-500 dark:text-slate-400">
          Workers affected by year, {years[0].period}–{years[years.length - 1].period}
        </div>
      )}
    </>
  );
}

export function CompanyPeek({ id, name }: { id: number; name: string }) {
  const { resolved } = useTheme();
  // The server-side rollup: every notice (merged dupes included), a few
  // hundred bytes, shared with the company page's cache.
  const summary = useQuery({
    queryKey: ["company", id, "summary"],
    queryFn: () => api.getCompanySummary(id),
  });
  const s = summary.data;
  const byYear = new Map((s?.by_year ?? []).map((r) => [r.year, r.layoff_total]));
  const series: number[] = [];
  if (s && s.by_year.length) {
    for (let y = s.by_year[0].year; y <= s.by_year[s.by_year.length - 1].year; y++) {
      series.push(byYear.get(y) ?? 0);
    }
  }
  // null when no notice published a count (no-counts states), so the card
  // says "—" rather than "0 workers".
  const workers = s ? (s.counted_notices ? s.layoff_total : null) : null;
  return (
    <>
      <div className="flex items-center gap-3">
        <CompanyLogo name={name} companyId={id} size={32} />
        <div className="min-w-0">
          <div className={KICKER}>All notices</div>
          <div className="truncate font-display text-base font-semibold">{name}</div>
        </div>
      </div>
      <Figures workers={workers} notices={s?.notice_count ?? null} />
      <Sparkline values={series} color={CHART_COLORS[resolved].layoffs} className="mt-2" />
      {s?.last_notice && (
        <div className="mt-1 text-[0.7rem] text-slate-500 dark:text-slate-400">
          Latest notice {fmtDate(s.last_notice)}
          {s.by_state.length > 0 &&
            ` · ${s.by_state.length} ${s.by_state.length === 1 ? "state" : "states"}`}
        </div>
      )}
    </>
  );
}

function Figures({ workers, notices }: { workers: number | null; notices: number | null }) {
  return (
    <div className="mt-2 flex items-baseline gap-3 tabular-nums">
      <span className="font-display text-xl font-semibold">{workers == null ? "—" : fmtNum(workers)}</span>
      <span className="text-xs text-slate-500 dark:text-slate-400">
        workers · {notices == null ? "—" : fmtNum(notices)} notices
      </span>
    </div>
  );
}
