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
  // One page of the company's notices is enough for a glance; the yearly
  // sums below say "most recent 200" when it is truncated.
  const notices = useQuery({
    queryKey: ["company", id, "notices", { limit: 200 }],
    queryFn: () => api.listCompanyNotices(id, { limit: 200 }),
  });
  const items = notices.data?.items ?? [];
  const byYear = new Map<string, number>();
  for (const n of items) {
    if (!n.notice_date) continue;
    const y = n.notice_date.slice(0, 4);
    byYear.set(y, (byYear.get(y) ?? 0) + (n.layoff_count ?? 0));
  }
  const yrs = [...byYear.keys()].sort();
  const series: number[] = [];
  if (yrs.length) {
    for (let y = Number(yrs[0]); y <= Number(yrs[yrs.length - 1]); y++) {
      series.push(byYear.get(String(y)) ?? 0);
    }
  }
  // Sum of published counts; null when no notice published one (no-counts
  // states), so the card says "—" rather than "0 workers".
  const counted = items.filter((n) => n.layoff_count != null);
  const workers = counted.length ? counted.reduce((a, n) => a + (n.layoff_count ?? 0), 0) : null;
  const truncated = (notices.data?.total ?? 0) > items.length;
  return (
    <>
      <div className="flex items-center gap-3">
        <CompanyLogo name={name} companyId={id} size={32} />
        <div className="min-w-0">
          <div className={KICKER}>{truncated ? "Latest 200 notices" : "All notices"}</div>
          <div className="truncate font-display text-base font-semibold">{name}</div>
        </div>
      </div>
      <Figures workers={workers} notices={notices.data?.total ?? null} />
      <Sparkline values={series} color={CHART_COLORS[resolved].layoffs} className="mt-2" />
      {items[0]?.notice_date && (
        <div className="mt-1 text-[0.7rem] text-slate-500 dark:text-slate-400">
          Latest notice {fmtDate(items[0].notice_date)} · {items[0].state}
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
