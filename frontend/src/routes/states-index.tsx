import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api/client";
import { QueryError } from "../components/QueryError";
import { UsChoroplethMap } from "../components/UsChoroplethMap";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { STATE_NAMES, US_STATES, fmtNum } from "../lib/format";

export function StatesIndexPage() {
  useDocumentTitle("Layoffs by state — WARN Tracker");

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
  })).sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Layoffs by state</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Browse WARN Act layoff and closure notices for each US state and DC.
        </p>
      </div>

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
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((s) => (
          <Link
            key={s.code}
            to="/states/$state"
            params={{ state: s.code }}
            className="card flex items-baseline justify-between hover:border-sky-300 hover:bg-sky-50 dark:hover:border-sky-800 dark:hover:bg-sky-950"
          >
            <div>
              <div className="font-medium text-slate-900 dark:text-slate-100">{s.name}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {fmtNum(s.notice_count)} {s.notice_count === 1 ? "notice" : "notices"}
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm font-semibold">{fmtNum(s.layoff_total)}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">workers</div>
            </div>
          </Link>
        ))}
      </div>
      </>
      )}
    </div>
  );
}
