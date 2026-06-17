import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import { AlertSignup } from "../components/AlertSignup";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { STATE_NAMES, fmtDate, fmtMonth, fmtNum, stateName } from "../lib/format";

export function StateDetailPage() {
  const { state } = useParams({ from: "/states/$state" });
  const code = state.toUpperCase();
  const valid = code in STATE_NAMES;
  const name = stateName(code);

  useDocumentTitle(
    valid ? `${name} layoffs & WARN notices — WARN Tracker` : "Unknown state — WARN Tracker",
  );

  // Hooks must run unconditionally; `enabled` keeps them idle for bad codes.
  const byState = useQuery({
    queryKey: ["stats", "by-state"],
    queryFn: () => api.statsByState(),
    enabled: valid,
  });
  const byMonth = useQuery({
    queryKey: ["stats", "by-month", { state: code }],
    queryFn: () => api.statsByMonth({ state: code }),
    enabled: valid,
  });
  const topEmployers = useQuery({
    queryKey: ["stats", "top-employers", { state: code }, 10],
    queryFn: () => api.statsTopEmployers({ state: code, limit: 10 }),
    enabled: valid,
  });
  const recent = useQuery({
    queryKey: ["notices", { state: code, limit: 10 }],
    queryFn: () => api.listNotices({ state: code, limit: 10 }),
    enabled: valid,
  });

  if (!valid) {
    return (
      <div className="card text-center">
        <p className="text-slate-700">Unknown state code “{state}”.</p>
        <Link to="/states" className="mt-2 inline-block text-sm font-medium text-sky-700 hover:underline">
          ← Browse all states
        </Link>
      </div>
    );
  }

  const row = byState.data?.find((s) => s.state === code);
  const noticeCount = row?.notice_count ?? 0;
  const layoffTotal = row?.layoff_total ?? 0;
  const monthData = (byMonth.data ?? []).map((r) => ({ ...r, monthLabel: fmtMonth(r.month) }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to="/states" className="text-sm font-medium text-sky-700 hover:underline">
            ← All states
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">{name} layoffs &amp; WARN notices</h1>
        </div>
        <div className="flex gap-3 text-sm">
          <Link
            to="/map"
            search={{ state: code }}
            className="font-medium text-sky-700 hover:underline"
          >
            View on map →
          </Link>
          <a
            href={`/states/${code}/feed.rss`}
            className="font-medium text-sky-700 hover:underline"
          >
            RSS
          </a>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500">Total notices</div>
          <div className="mt-1 text-3xl font-semibold">{fmtNum(noticeCount)}</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500">Workers affected</div>
          <div className="mt-1 text-3xl font-semibold">{fmtNum(layoffTotal)}</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500">Most recent notice</div>
          <div className="mt-1 text-3xl font-semibold">
            {fmtDate(recent.data?.items[0]?.notice_date)}
          </div>
        </div>
      </div>

      <AlertSignup state={code} />

      <div className="card">
        <h2 className="mb-3 text-lg font-semibold">Notices and layoffs by month</h2>
        {byMonth.isLoading ? (
          <div className="flex h-72 items-center justify-center text-slate-500">Loading…</div>
        ) : monthData.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-sm text-slate-500">
            No notices recorded for {name} yet.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={monthData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="monthLabel" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v: number) => fmtNum(v)} />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="notice_count"
                name="Notices"
                stroke="#0369a1"
                strokeWidth={2}
                dot={false}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="layoff_total"
                name="Workers affected"
                stroke="#dc2626"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section>
          <h2 className="mb-2 text-lg font-semibold">Top employers</h2>
          <div className="card divide-y divide-slate-100 p-0">
            {topEmployers.isLoading && (
              <div className="p-4 text-sm text-slate-500">Loading…</div>
            )}
            {topEmployers.data?.length === 0 && (
              <div className="p-4 text-sm text-slate-500">No data yet.</div>
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
                </div>
                <div className="shrink-0 text-sm font-medium">{fmtNum(e.layoff_total)}</div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Recent notices</h2>
            <Link
              to="/notices"
              search={{ state: code }}
              className="text-sm font-medium text-sky-700 hover:underline"
            >
              View all →
            </Link>
          </div>
          <div className="card divide-y divide-slate-100 p-0">
            {recent.isLoading && <div className="p-4 text-sm text-slate-500">Loading…</div>}
            {recent.data?.items.length === 0 && (
              <div className="p-4 text-sm text-slate-500">No notices yet.</div>
            )}
            {recent.data?.items.map((n) => (
              <Link
                key={n.notice_id}
                to="/notices/$noticeId"
                params={{ noticeId: n.notice_id }}
                className="block px-4 py-3 hover:bg-slate-50"
              >
                <div className="flex items-baseline justify-between gap-4">
                  <div className="min-w-0 truncate font-medium">{n.employer}</div>
                  <div className="shrink-0 text-xs text-slate-500">{fmtDate(n.notice_date)}</div>
                </div>
                <div className="text-xs text-slate-500">
                  {n.layoff_count != null && <span>{fmtNum(n.layoff_count)} affected · </span>}
                  {n.location?.city || n.location?.county || "Location unspecified"}
                </div>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
