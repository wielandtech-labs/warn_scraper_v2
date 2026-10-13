import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { QueryError } from "../components/QueryError";
import { StateSilhouette } from "../components/StateSilhouette";
import { UsChoroplethMap } from "../components/UsChoroplethMap";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { STATE_NAMES, US_STATES, fmtNum } from "../lib/format";
import { NO_COUNTS, UNSUPPORTED } from "../lib/unavailable";

type SortKey = "name" | "workers" | "notices";
const SORTS: { id: SortKey; label: string }[] = [
  { id: "workers", label: "Most workers" },
  { id: "notices", label: "Most notices" },
  { id: "name", label: "A–Z" },
];

export function StatesIndexPage() {
  useDocumentTitle("Layoffs by state — WARN Index");
  const [sort, setSort] = useState<SortKey>("workers");

  const byState = useQuery({
    queryKey: ["stats", "by-state"],
    queryFn: () => api.statsByState(),
  });

  // Index the aggregate by state code; states with no notices still render
  // (zeros), so every jurisdiction has a browsable, internally-linked page.
  const stats = new Map(
    (byState.data ?? []).map((s) => [s.state, s]),
  );
  const rows = US_STATES.map((code) => ({
    code,
    name: STATE_NAMES[code],
    notice_count: stats.get(code)?.notice_count ?? 0,
    layoff_total: stats.get(code)?.layoff_total ?? 0,
  })).sort((a, b) =>
    sort === "workers"
      ? b.layoff_total - a.layoff_total || a.name.localeCompare(b.name)
      : sort === "notices"
        ? b.notice_count - a.notice_count || a.name.localeCompare(b.name)
        : a.name.localeCompare(b.name),
  );
  // Card bars share one scale: the largest state's total for the active sort.
  const barMax = Math.max(
    1,
    ...rows.map((r) => (sort === "notices" ? r.notice_count : r.layoff_total)),
  );
  const reporting = (byState.data ?? []).filter((s) => s.notice_count > 0).length;
  const totalWorkers = (byState.data ?? []).reduce((a, s) => a + s.layoff_total, 0);

  return (
    <div className="space-y-6">
      <PageHeader
        kicker="50 states + DC"
        title="Layoffs by state"
        lede={
          byState.data ? (
            <>
              <span className="font-semibold text-slate-900 dark:text-slate-100">
                {fmtNum(totalWorkers)}
              </span>{" "}
              workers affected across {reporting} jurisdictions that publish WARN notices. Open
              a state for its trend, top employers and latest filings.
            </>
          ) : (
            "Browse WARN Act layoff and closure notices for each US state and DC."
          )
        }
      />

      {byState.isLoading && (
        <div aria-hidden className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className="card animate-pulse space-y-2">
              <div className="h-4 w-1/2 rounded bg-slate-200 dark:bg-slate-700" />
              <div className="h-3 w-1/3 rounded bg-slate-200 dark:bg-slate-700" />
            </div>
          ))}
        </div>
      )}

      {byState.isError && (
        <QueryError
          message="Error loading state totals."
          onRetry={() => byState.refetch()}
        />
      )}

      {/* Don't render the grid until data arrives — with no data every state
          would confidently show zeros. */}
      {byState.data && (
      <>
      <UsChoroplethMap data={rows} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Every jurisdiction</h2>
        <div
          role="group"
          aria-label="Sort states"
          className="inline-flex rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900"
        >
          {SORTS.map((s) => (
            <button
              key={s.id}
              type="button"
              aria-pressed={sort === s.id}
              onClick={() => setSort(s.id)}
              className={
                "rounded-full px-3 py-1 text-xs font-medium transition-colors " +
                (sort === s.id
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100")
              }
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((s) => {
          // NO_COUNTS: the source publishes no employee counts, so a zero would
          // misread as "no workers affected". UNSUPPORTED: nothing published.
          const noCounts = s.code in NO_COUNTS;
          const unsupported = s.code in UNSUPPORTED;
          const barValue = sort === "notices" ? s.notice_count : noCounts ? 0 : s.layoff_total;
          return (
            <Link
              key={s.code}
              to="/states/$state"
              params={{ state: s.code }}
              className="card group flex flex-col gap-3 transition-colors hover:border-slate-300 dark:hover:border-slate-700"
            >
              <div className="flex items-center gap-3">
                <StateSilhouette
                  code={s.code}
                  size={36}
                  className="shrink-0 text-slate-300 transition-colors group-hover:text-brand dark:text-slate-600"
                />
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-slate-900 dark:text-slate-100">{s.name}</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {unsupported
                      ? "No notices published"
                      : `${fmtNum(s.notice_count)} ${s.notice_count === 1 ? "notice" : "notices"}`}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-display text-lg font-semibold tabular-nums">
                    {noCounts || unsupported ? "—" : fmtNum(s.layoff_total)}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {unsupported ? "not published" : noCounts ? "counts not published" : "workers"}
                  </div>
                </div>
              </div>
              {sort !== "name" && (
                <div aria-hidden className="h-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div
                    // Entity colors, as in the charts: workers red, notices blue.
                    className={`h-full rounded-full ${sort === "notices" ? "bg-sky-500/70" : "bg-brand/70"}`}
                    style={{ width: `${(barValue / barMax) * 100}%` }}
                  />
                </div>
              )}
            </Link>
          );
        })}
      </div>
      </>
      )}
    </div>
  );
}
