import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api/client";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { STATE_NAMES, US_STATES, fmtDate, fmtNum } from "../lib/format";
import { UNSUPPORTED } from "../lib/unavailable";

type Health = "operational" | "failing" | "unsupported" | "never";

const BADGE: Record<Health, { label: string; className: string }> = {
  operational: { label: "Operational", className: "badge-green" },
  failing: { label: "Failing", className: "badge-red" },
  unsupported: { label: "No public source", className: "badge-slate" },
  never: { label: "Never run", className: "badge-slate" },
};

// Failing first (that's the point of the page), then operational, then the rest.
const SEVERITY: Record<Health, number> = {
  failing: 0,
  operational: 1,
  unsupported: 2,
  never: 2,
};

/** Short "x days ago" suffix for a last-success timestamp. */
function relDays(iso: string | null | undefined): string {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 60) return `${days} days ago`;
  return `${Math.floor(days / 30)} months ago`;
}

export function StatusPage() {
  useDocumentTitle("Scraper status — WARN Tracker");

  const statusQuery = useQuery({
    queryKey: ["scraper-status"],
    queryFn: () => api.listScraperStatus(),
  });

  const byState = new Map((statusQuery.data ?? []).map((s) => [s.state, s]));

  const rows = US_STATES.map((code) => {
    const run = byState.get(code);
    let health: Health;
    if (code in UNSUPPORTED) health = "unsupported";
    else if (!run) health = "never";
    else if (run.last_status === "ok") health = "operational";
    else health = "failing";
    return { code, name: STATE_NAMES[code], run, health };
  }).sort(
    (a, b) =>
      SEVERITY[a.health] - SEVERITY[b.health] || a.name.localeCompare(b.name),
  );

  const counts = {
    operational: rows.filter((r) => r.health === "operational").length,
    failing: rows.filter((r) => r.health === "failing").length,
    other: rows.filter((r) => r.health === "unsupported" || r.health === "never")
      .length,
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Scraper status</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Health of each state scraper and when it last successfully updated.
          Scrapers run daily; a state is “operational” when its most recent run
          succeeded.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Operational</div>
          <div className="mt-1 text-3xl font-semibold text-green-700 dark:text-green-400">
            {fmtNum(counts.operational)}
          </div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Failing</div>
          <div className="mt-1 text-3xl font-semibold text-red-700 dark:text-red-400">
            {fmtNum(counts.failing)}
          </div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
            No public source / never run
          </div>
          <div className="mt-1 text-3xl font-semibold text-slate-700 dark:text-slate-300">
            {fmtNum(counts.other)}
          </div>
        </div>
      </div>

      {statusQuery.isLoading && (
        <div className="card text-center text-sm text-slate-500 dark:text-slate-400">Loading…</div>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="data-table w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-950 dark:text-slate-400">
            <tr>
              <th className="px-3 py-2 font-medium">State</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Last successful scrape</th>
              <th className="px-3 py-2 font-medium">Last run</th>
              <th className="px-3 py-2 font-medium">New / scraped</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((r) => {
              const badge = BADGE[r.health];
              const reason = UNSUPPORTED[r.code];
              return (
                <tr key={r.code} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td className="px-3 py-2 align-top" data-label="State">
                    <Link
                      to="/states/$state"
                      params={{ state: r.code }}
                      className="font-medium text-slate-900 hover:underline dark:text-slate-100"
                    >
                      {r.name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 align-top" data-label="Status">
                    <span
                      className={badge.className}
                      title={reason ?? r.run?.error ?? undefined}
                    >
                      {badge.label}
                    </span>
                  </td>
                  <td className="px-3 py-2 align-top" data-label="Last successful scrape">
                    {r.run?.last_success_at ? (
                      <span>
                        {fmtDate(r.run.last_success_at)}{" "}
                        <span className="text-xs text-slate-500 dark:text-slate-400">
                          ({relDays(r.run.last_success_at)})
                        </span>
                      </span>
                    ) : (
                      <span className="text-slate-400 dark:text-slate-500">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 align-top" data-label="Last run">
                    {r.run ? (
                      fmtDate(r.run.last_run_at)
                    ) : (
                      <span className="text-slate-400 dark:text-slate-500">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 align-top" data-label="New / scraped">
                    {r.run && r.run.rows_scraped != null ? (
                      <span>
                        {fmtNum(r.run.rows_new)} / {fmtNum(r.run.rows_scraped)}
                      </span>
                    ) : (
                      <span className="text-slate-400 dark:text-slate-500">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        “No public source” marks jurisdictions with no scrapable WARN listing
        (state law or no online source) — hover the badge for details. Counts
        cover all {US_STATES.length} US jurisdictions (50 states + DC).
      </p>
    </div>
  );
}
