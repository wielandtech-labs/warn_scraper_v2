import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, ApiError } from "../api/client";
import { AlertSignup } from "../components/AlertSignup";
import { CompanyLogo } from "../components/CompanyLogo";
import { ForecastNote } from "../components/ForecastNote";
import { HeroMap } from "../components/HeroMap";
import { QueryError } from "../components/QueryError";
import { SkeletonChart, SkeletonRows } from "../components/Skeleton";
import {
  TimeRangeToggle,
  toRangeQuery,
  type TimeRange,
} from "../components/TimeRangeToggle";
import { ProjectionNote } from "../components/ProjectionNote";
import { WarnTimeChart } from "../components/WarnTimeChart";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useTheme } from "../hooks/useTheme";
import { BLS_LABOUR_MARKET } from "../lib/blsSeries";
import { fmtCompact, fmtDate, fmtNum, fmtPeriod } from "../lib/format";
import { withForecastSeries } from "../lib/forecast";
import { withProjectionSeries } from "../lib/projection";
import { CHART_COLORS } from "../lib/themeColors";

const RANGE_LABEL: Record<TimeRange, string> = {
  "30d": "last 30 days",
  "1y": "past year",
  "5y": "past 5 years",
  all: "all time",
};

export function Dashboard() {
  useDocumentTitle("WARN Index — US layoff & closure notices");
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
    queryKey: ["stats", "top-employers", { after }, 10],
    queryFn: () => api.statsTopEmployers({ limit: 10, after }),
  });

  // Complete periods only for the hero sparkline: the current partial period
  // (projected_* set) would read as a collapse.
  const nationalSeries = (overTime.data ?? []).map((r) =>
    r.projected_notice_count != null ? null : r.layoff_total,
  );

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
    <div className="space-y-8">
      <HeroMap
        byState={byState.data}
        bucket={bucket}
        after={after}
        rangeLabel={RANGE_LABEL[range]}
        national={nationalSeries}
        controls={<TimeRangeToggle value={range} onChange={setRange} />}
      />
      {byState.isError && (
        <QueryError message="Error loading state totals." onRetry={() => byState.refetch()} />
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Above the charts because, unlike them, it doesn't follow the
            time-range toggle — it's always the newest notices. */}
        <section className="lg:col-span-2">
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
                className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50"
              >
                <CompanyLogo
                  name={n.company?.name ?? n.employer}
                  companyId={n.company?.id}
                  hasWebsite={!!n.company?.website}
                />
                <div className="min-w-0 flex-1">
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
                </div>
              </Link>
            ))}
          </div>
        </section>
        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Top employers</h2>
            <span className="text-xs text-slate-500 dark:text-slate-400">by workers affected</span>
          </div>
          <div className="card divide-y divide-slate-100 p-0 dark:divide-slate-800">
            {topEmployers.isLoading && <SkeletonRows rows={5} />}
            {topEmployers.data?.map((e) => (
              <div key={e.employer} className="flex items-center gap-3 px-4 py-3">
                <CompanyLogo name={e.employer} companyId={e.company_id} />
                <div className="min-w-0 flex-1 truncate">
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
            <WarnTimeChart
              rows={timeData}
              bucket={bucket}
              subject="across the US"
              bls={{ options: BLS_LABOUR_MARKET, after }}
            />
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
                <CartesianGrid stroke={chart.grid} />
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
                <Bar dataKey="layoff_total" name="Workers affected" fill={chart.layoffs} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

    </div>
  );
}
