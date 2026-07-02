import { useState } from "react";
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
import { NoticeMap } from "../components/NoticeMap";
import {
  TimeRangeToggle,
  toRangeQuery,
  type TimeRange,
} from "../components/TimeRangeToggle";
import { UnavailableNotice } from "../components/UnavailableNotice";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { STATE_NAMES, fmtDate, fmtNum, fmtPeriod, stateName } from "../lib/format";
import { LAW_BLOCKED } from "../lib/unavailable";

export function StateDetailPage() {
  const { state } = useParams({ from: "/states/$state" });
  const code = state.toUpperCase();
  const valid = code in STATE_NAMES;
  // State law blocks publication of these states' notices — no data will ever
  // arrive, so skip the stats fetches and show an explainer instead.
  const blocked = code in LAW_BLOCKED;
  const name = stateName(code);

  useDocumentTitle(
    valid ? `${name} layoffs & WARN notices — WARN Tracker` : "Unknown state — WARN Tracker",
  );

  const [range, setRange] = useState<TimeRange>("all");
  const { after, bucket } = toRangeQuery(range);

  // Hooks must run unconditionally; `enabled` keeps them idle for bad codes.
  const byState = useQuery({
    queryKey: ["stats", "by-state", { after }],
    queryFn: () => api.statsByState({ after }),
    enabled: valid && !blocked,
  });
  const overTime = useQuery({
    queryKey: ["stats", "over-time", { state: code, after, bucket }],
    queryFn: () => api.statsOverTime({ state: code, after, bucket }),
    enabled: valid && !blocked,
  });
  const topEmployers = useQuery({
    queryKey: ["stats", "top-employers", { state: code, after }, 10],
    queryFn: () => api.statsTopEmployers({ state: code, after, limit: 10 }),
    enabled: valid && !blocked,
  });
  const recent = useQuery({
    queryKey: ["notices", { state: code, after, limit: 10 }],
    queryFn: () => api.listNotices({ state: code, after, limit: 10 }),
    enabled: valid && !blocked,
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

  if (blocked) {
    return (
      <div className="space-y-6">
        <div>
          <Link to="/states" className="text-sm font-medium text-sky-700 hover:underline">
            ← All states
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">{name} layoffs &amp; WARN notices</h1>
        </div>
        <UnavailableNotice state={code} />
      </div>
    );
  }

  const row = byState.data?.find((s) => s.state === code);
  const noticeCount = row?.notice_count ?? 0;
  const layoffTotal = row?.layoff_total ?? 0;
  const timeData = (overTime.data ?? []).map((r) => ({
    ...r,
    label: fmtPeriod(r.period, bucket),
  }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to="/states" className="text-sm font-medium text-sky-700 hover:underline">
            ← All states
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">{name} layoffs &amp; WARN notices</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <TimeRangeToggle value={range} onChange={setRange} />
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
        <h2 className="mb-3 text-lg font-semibold">Notices and layoffs over time</h2>
        {overTime.isLoading ? (
          <div className="flex h-72 items-center justify-center text-slate-500">Loading…</div>
        ) : timeData.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-sm text-slate-500">
            No notices recorded for {name} in this period.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={timeData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" tick={{ fontSize: 12 }} minTickGap={24} />
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

      <div className="card">
        <h2 className="mb-3 text-lg font-semibold">Layoffs across {name}</h2>
        <NoticeMap state={code} after={after} />
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
