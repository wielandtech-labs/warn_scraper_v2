import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api/client";
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
        <p className="mt-1 text-sm text-slate-600">
          Browse WARN Act layoff and closure notices for each US state and DC.
        </p>
      </div>

      {byState.isLoading && (
        <div className="card text-center text-sm text-slate-500">Loading…</div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((s) => (
          <Link
            key={s.code}
            to="/states/$state"
            params={{ state: s.code }}
            className="card flex items-baseline justify-between hover:border-sky-300 hover:bg-sky-50"
          >
            <div>
              <div className="font-medium text-slate-900">{s.name}</div>
              <div className="text-xs text-slate-500">
                {fmtNum(s.notice_count)} {s.notice_count === 1 ? "notice" : "notices"}
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm font-semibold">{fmtNum(s.layoff_total)}</div>
              <div className="text-xs text-slate-500">workers</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
