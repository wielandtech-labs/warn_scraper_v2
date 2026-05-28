import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api/client";
import { fmtDate, fmtNum } from "../lib/format";

export function Dashboard() {
  const recent = useQuery({
    queryKey: ["notices", { limit: 10 }],
    queryFn: () => api.listNotices({ limit: 10 }),
  });

  const byState = useQuery({
    queryKey: ["stats", "by-state"],
    queryFn: () => api.statsByState(),
  });

  const topEmployers = useQuery({
    queryKey: ["stats", "top-employers", 5],
    queryFn: () => api.statsTopEmployers({ limit: 5 }),
  });

  const totalLayoffs =
    byState.data?.reduce((acc, s) => acc + s.layoff_total, 0) ?? null;
  const totalNotices = byState.data?.reduce((acc, s) => acc + s.notice_count, 0) ?? null;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500">
            Total notices
          </div>
          <div className="mt-1 text-3xl font-semibold">{fmtNum(totalNotices)}</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500">
            Workers affected
          </div>
          <div className="mt-1 text-3xl font-semibold">{fmtNum(totalLayoffs)}</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500">
            States covered
          </div>
          <div className="mt-1 text-3xl font-semibold">
            {fmtNum(byState.data?.length ?? null)}
          </div>
        </div>
      </div>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Recent notices</h2>
          <Link to="/notices" className="text-sm font-medium text-sky-700 hover:underline">
            View all →
          </Link>
        </div>
        <div className="card divide-y divide-slate-100 p-0">
          {recent.isLoading && <div className="p-4 text-sm text-slate-500">Loading…</div>}
          {recent.data?.items.map((n) => (
            <Link
              key={n.notice_id}
              to="/notices/$noticeId"
              params={{ noticeId: n.notice_id }}
              className="block px-4 py-3 hover:bg-slate-50"
            >
              <div className="flex items-baseline justify-between gap-4">
                <div className="min-w-0 truncate font-medium">{n.employer}</div>
                <div className="shrink-0 text-xs text-slate-500">
                  {fmtDate(n.notice_date)} · {n.state}
                </div>
              </div>
              <div className="text-xs text-slate-500">
                {n.layoff_count != null && <span>{fmtNum(n.layoff_count)} affected · </span>}
                {n.location?.city || n.location?.county || "Location unspecified"}
              </div>
            </Link>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Top employers (by layoff count)</h2>
        <div className="card divide-y divide-slate-100 p-0">
          {topEmployers.isLoading && (
            <div className="p-4 text-sm text-slate-500">Loading…</div>
          )}
          {topEmployers.data?.map((e) => (
            <div key={e.employer} className="flex items-baseline justify-between px-4 py-3">
              <div className="min-w-0 truncate">
                {e.company_id ? (
                  <Link
                    to="/companies/$companyId"
                    params={{ companyId: String(e.company_id) }}
                    className="font-medium text-slate-900 hover:underline"
                  >
                    {e.employer}
                  </Link>
                ) : (
                  <span className="font-medium">{e.employer}</span>
                )}
                <span className="ml-2 text-xs text-slate-500">
                  {e.notice_count} {e.notice_count === 1 ? "notice" : "notices"}
                </span>
              </div>
              <div className="shrink-0 text-sm font-medium">{fmtNum(e.layoff_total)}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
