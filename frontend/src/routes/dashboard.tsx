import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import { AlertSignup } from "../components/AlertSignup";
import { QueryError } from "../components/QueryError";
import { SkeletonBlock, SkeletonChart, SkeletonRows } from "../components/Skeleton";
import {
  TimeRangeToggle,
  toRangeQuery,
  type TimeRange,
} from "../components/TimeRangeToggle";
import { ProjectionNote } from "../components/ProjectionNote";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtCompact, fmtDate, fmtNum, fmtPeriod } from "../lib/format";
import { projectionTooltip, withProjectionSeries } from "../lib/projection";

export function Dashboard() {
  useDocumentTitle("WARN Tracker — US layoff & closure notices");
  const [range, setRange] = useState<TimeRange>("all");
  const { after, bucket } = toRangeQuery(range);

  const recent = useQuery({
    queryKey: ["notices", { limit: 10, after }],
    queryFn: () => api.listNotices({ limit: 10, after }),
  });

  const byState = useQuery({
    queryKey: ["stats", "by-state", { after }],
    queryFn: () => api.statsByState({ after }),
  });

  const overTime = useQuery({
    queryKey: ["stats", "over-time", { after, bucket }],
    queryFn: () => api.statsOverTime({ after, bucket }),
  });

  const industries = useQuery({
    queryKey: ["stats", "industries", { after }],
    queryFn: () => api.statsIndustries({ after }),
  });

  const topEmployers = useQuery({
    queryKey: ["stats", "top-employers", { after }, 5],
    queryFn: () => api.statsTopEmployers({ limit: 5, after }),
  });

  const totalLayoffs =
    byState.data?.reduce((acc, s) => acc + s.layoff_total, 0) ?? null;
  const totalNotices = byState.data?.reduce((acc, s) => acc + s.notice_count, 0) ?? null;

  const { data: timeData, hasProjection } = withProjectionSeries(
    (overTime.data ?? []).map((r) => ({
      ...r,
      label: fmtPeriod(r.period, bucket),
    })),
  );
  const industryData = (industries.data ?? [])
    .slice()
    .sort((a, b) => b.layoff_total - a.layoff_total);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <TimeRangeToggle value={range} onChange={setRange} />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Total notices
          </div>
          <div className="mt-1 text-3xl font-semibold">
            {byState.isLoading ? <SkeletonBlock className="h-9 w-24" /> : fmtNum(totalNotices)}
          </div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Workers affected
          </div>
          <div className="mt-1 text-3xl font-semibold">
            {byState.isLoading ? <SkeletonBlock className="h-9 w-24" /> : fmtNum(totalLayoffs)}
          </div>
        </div>
        <div className="card">
          <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
            States covered
          </div>
          <div className="mt-1 text-3xl font-semibold">
            {byState.isLoading ? (
              <SkeletonBlock className="h-9 w-24" />
            ) : (
              fmtNum(byState.data?.length ?? null)
            )}
          </div>
        </div>
      </div>

      <AlertSignup />

      <div className="card">
        <h2 className="mb-3 text-lg font-semibold">Layoffs over time</h2>
        {overTime.isLoading ? (
          <SkeletonChart height={300} />
        ) : overTime.isError ? (
          <QueryError
            message="Error loading the layoffs-over-time chart."
            onRetry={() => overTime.refetch()}
          />
        ) : timeData.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
            No notices in this period.
          </div>
        ) : (
          <>
            <div
              role="img"
              aria-label="Line chart of notice counts and workers affected over time"
            >
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={timeData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 12 }} minTickGap={24} />
                  {/* Axis ticks are colored to match their series, so the dual
                      axes are readable without cross-referencing the legend. */}
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 12, fill: "#0369a1" }}
                    tickFormatter={fmtCompact}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 12, fill: "#dc2626" }}
                    tickFormatter={fmtCompact}
                  />
                  <Tooltip formatter={projectionTooltip} />
                  <Legend />
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
                  {/* Dashed pace projection for the current, incomplete period;
                      all-null (invisible) when no projection is active. */}
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="projected_notice_count"
                    name="Notices (projected)"
                    stroke="#0369a1"
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    dot={false}
                    legendType="none"
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="projected_layoff_total"
                    name="Workers affected (projected)"
                    stroke="#dc2626"
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    dot={false}
                    legendType="none"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            {hasProjection && (
              <ProjectionNote periodLabel={timeData[timeData.length - 1].label} />
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2 className="mb-3 text-lg font-semibold">Workers affected by industry</h2>
        {industries.isLoading ? (
          <SkeletonChart height={288} />
        ) : industries.isError ? (
          <QueryError
            message="Error loading the industry chart."
            onRetry={() => industries.refetch()}
          />
        ) : industryData.length === 0 ? (
          <div className="flex h-24 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
            No industry data for this period.
          </div>
        ) : (
          <div role="img" aria-label="Bar chart of workers affected by industry">
            <ResponsiveContainer width="100%" height={Math.max(240, industryData.length * 28)}>
              <BarChart layout="vertical" data={industryData} margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={fmtCompact} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 11 }} width={180} />
                <Tooltip formatter={(v: number) => fmtNum(v)} />
                <Bar dataKey="layoff_total" name="Workers affected" fill="#0369a1" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Recent notices</h2>
          <Link to="/notices" className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
            View all →
          </Link>
        </div>
        <div className="card divide-y divide-slate-100 p-0 dark:divide-slate-800">
          {recent.isLoading && <SkeletonRows rows={5} />}
          {recent.isError && (
            <div className="p-4">
              <QueryError
                message="Error loading recent notices."
                onRetry={() => recent.refetch()}
              />
            </div>
          )}
          {recent.data?.items.map((n) => (
            <Link
              key={n.notice_id}
              to="/notices/$noticeId"
              params={{ noticeId: n.notice_id }}
              className="block px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <div className="flex items-baseline justify-between gap-4">
                <div className="min-w-0 truncate font-medium">{n.employer}</div>
                <div className="shrink-0 text-xs text-slate-500 dark:text-slate-400">
                  {fmtDate(n.notice_date)} · {n.state}
                </div>
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {n.layoff_count != null && <span>{fmtNum(n.layoff_count)} affected · </span>}
                {n.location?.city || n.location?.county || "Location unspecified"}
              </div>
            </Link>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Top employers (by layoff count)</h2>
        <div className="card divide-y divide-slate-100 p-0 dark:divide-slate-800">
          {topEmployers.isLoading && <SkeletonRows rows={5} />}
          {topEmployers.data?.map((e) => (
            <div key={e.employer} className="flex items-baseline justify-between px-4 py-3">
              <div className="min-w-0 truncate">
                {e.company_id ? (
                  <Link
                    to="/companies/$companyId"
                    params={{ companyId: String(e.company_id) }}
                    className="font-medium text-slate-900 hover:underline dark:text-slate-100"
                  >
                    {e.employer}
                  </Link>
                ) : (
                  <span className="font-medium">{e.employer}</span>
                )}
                <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
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
