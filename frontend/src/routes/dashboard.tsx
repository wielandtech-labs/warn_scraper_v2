import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, ApiError } from "../api/client";
import { AlertSignup } from "../components/AlertSignup";
import { ForecastNote } from "../components/ForecastNote";
import { QueryError } from "../components/QueryError";
import { SkeletonBlock, SkeletonChart, SkeletonRows } from "../components/Skeleton";
import {
  TimeRangeToggle,
  toRangeQuery,
  type TimeRange,
} from "../components/TimeRangeToggle";
import { ProjectionNote } from "../components/ProjectionNote";
import { ProjectionTooltip } from "../components/ProjectionTooltip";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useTheme } from "../hooks/useTheme";
import { fmtCompact, fmtDate, fmtNum, fmtPeriod } from "../lib/format";
import { withForecastSeries } from "../lib/forecast";
import { withProjectionSeries } from "../lib/projection";
import { CHART_COLORS } from "../lib/themeColors";

export function Dashboard() {
  useDocumentTitle("WARN Tracker — US layoff & closure notices");
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];
  const [range, setRange] = useState<TimeRange>("all");
  const { after, bucket } = toRangeQuery(range);

  // Deliberately not filtered by the time-range toggle: this is a live feed of
  // the newest notices, so a bounded window would never visibly change it.
  const recent = useQuery({
    queryKey: ["notices", { limit: 10 }],
    queryFn: () => api.listNotices({ limit: 10 }),
  });

  const byState = useQuery({
    queryKey: ["stats", "by-state", { after }],
    queryFn: () => api.statsByState({ after }),
  });

  const overTime = useQuery({
    queryKey: ["stats", "over-time", { after, bucket }],
    queryFn: () => api.statsOverTime({ after, bucket }),
  });

  // Weekly statistical forecast, national roll-up. A 404 just means the
  // jurisdiction never cleared the lowest forecast model tier (or the job
  // hasn't run yet) — don't retry, and fall back to the pace projection.
  const forecast = useQuery({
    queryKey: ["forecast", "US"],
    queryFn: () => api.getForecast("US"),
    enabled: bucket === "month",
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
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

  const labeledTimeData = (overTime.data ?? []).map((r) => ({
    ...r,
    label: fmtPeriod(r.period, bucket),
  }));
  const { data: forecastData, hasForecast } = withForecastSeries(
    labeledTimeData,
    forecast.data,
    bucket,
  );
  // The forecast supersedes the pace projection when active — an ETS point
  // estimate beats a linear pace estimate, and two overlapping dashed
  // segments would just be noise.
  const { data: projectedData, hasProjection } = withProjectionSeries(labeledTimeData);
  const timeData = hasForecast ? forecastData : projectedData;
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

      {/* Above the charts because, unlike them, it doesn't follow the
          time-range toggle — it's always the newest notices. */}
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
                <ComposedChart data={timeData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 12, fill: chart.axis }}
                    minTickGap={24}
                  />
                  {/* Axis ticks are colored to match their series, so the dual
                      axes are readable without cross-referencing the legend. */}
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 12, fill: chart.notices }}
                    tickFormatter={fmtCompact}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 12, fill: chart.layoffs }}
                    tickFormatter={fmtCompact}
                  />
                  <Tooltip
                    content={<ProjectionTooltip />}
                    contentStyle={chart.tooltip}
                    labelStyle={chart.tooltipLabel}
                  />
                  <Legend />
                  {/* 80% prediction-interval band for the forecast — layoffs
                      only, so it doesn't compete visually with a second band
                      for notices. All-null (invisible) when no forecast. */}
                  <Area
                    yAxisId="right"
                    type="monotone"
                    dataKey="forecast_layoff_band"
                    name="Workers affected (forecast range)"
                    fill={chart.layoffs}
                    fillOpacity={0.12}
                    stroke="none"
                    legendType="none"
                    animationBegin={1500}
                    isAnimationActive={false}
                  />
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="notice_count"
                    name="Notices"
                    stroke={chart.notices}
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="layoff_total"
                    name="Workers affected"
                    stroke={chart.layoffs}
                    strokeWidth={2}
                    dot={false}
                  />
                  {/* Dashed pace projection for the current, incomplete period;
                      all-null (invisible) when no projection is active.
                      animationBegin waits out the solid lines' default 1500ms
                      draw so the projection appears after them, not before. */}
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="projected_notice_count"
                    name="Notices (projected)"
                    stroke={chart.notices}
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    animationBegin={1500}
                    dot={false}
                    legendType="none"
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="projected_layoff_total"
                    name="Workers affected (projected)"
                    stroke={chart.layoffs}
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    animationBegin={1500}
                    dot={false}
                    legendType="none"
                  />
                  {/* Dashed 6-month forecast; supersedes the projection above
                      when active (both are all-null otherwise). */}
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="forecast_notice_count"
                    name="Notices (forecast)"
                    stroke={chart.notices}
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    animationBegin={1500}
                    dot={false}
                    legendType="none"
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="forecast_layoff_total"
                    name="Workers affected (forecast)"
                    stroke={chart.layoffs}
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    animationBegin={1500}
                    dot={false}
                    legendType="none"
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            {hasForecast && forecast.data ? (
              <ForecastNote lastHistoryLabel={fmtPeriod(forecast.data.last_history_month, "month")} />
            ) : (
              hasProjection && (
                <ProjectionNote periodLabel={timeData[timeData.length - 1].label} />
              )
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
                <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 12, fill: chart.axis }}
                  tickFormatter={fmtCompact}
                />
                <YAxis
                  dataKey="name"
                  type="category"
                  tick={{ fontSize: 11, fill: chart.axis }}
                  width={180}
                />
                <Tooltip
                  formatter={(v: number) => fmtNum(v)}
                  contentStyle={chart.tooltip}
                  labelStyle={chart.tooltipLabel}
                  cursor={{ fill: chart.cursor }}
                />
                <Bar dataKey="layoff_total" name="Workers affected" fill={chart.notices} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

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
