import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import { ActiveFilters } from "../components/ActiveFilters";
import { BlsLevels } from "../components/BlsLevels";
import { CountyImpact } from "../components/CountyImpact";
import { EmployerRanking } from "../components/EmployerRanking";
import { Figure, Figures } from "../components/Figures";
import { IndicatorChart } from "../components/IndicatorChart";
import { FilterBar, type FilterValues } from "../components/FilterBar";
import { resolveAfter } from "../lib/filters";
import { PageHeader } from "../components/PageHeader";
import { ProjectionNote } from "../components/ProjectionNote";
import { QueryError } from "../components/QueryError";
import { SkeletonChart, SkeletonRows } from "../components/Skeleton";
import { WarnTimeChart } from "../components/WarnTimeChart";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useTheme } from "../hooks/useTheme";
import { BLS_LABOUR_MARKET } from "../lib/blsSeries";
import { fmtCompact, fmtDate, fmtMonth, fmtNum, stateName } from "../lib/format";
import { withProjectionSeries } from "../lib/projection";
import { CHART_COLORS } from "../lib/themeColors";

// With no dates set the page opens on the last five years rather than all
// time: the full span is dominated by the 2020 spike and by early years that
// mostly show states joining our coverage. "All" is one click away.
const DEFAULT_DAYS = 365 * 5;

export function StatsPage() {
  useDocumentTitle("Layoff statistics & trends — WARN Index");
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];
  const navigate = useNavigate({ from: "/stats" });
  const urlSearch = useSearch({ from: "/stats" });
  // Everything below queries with the resolved window; only the FilterBar
  // sees the raw URL params.
  const search = { ...urlSearch, after: resolveAfter(urlSearch, DEFAULT_DAYS) };

  const byMonth = useQuery({
    queryKey: ["stats", "by-month", search],
    queryFn: () => api.statsByMonth(search),
  });

  // /api/stats/by-state takes no state param, so this chart cannot honor a state
  // filter — the card is hidden while one is set, and the fetch skipped with it.
  const byStateParams = {
    closure_category: search.closure_category,
    industry: search.industry,
    subsector: search.subsector,
    after: search.after,
    before: search.before,
  };
  const byState = useQuery({
    queryKey: ["stats", "by-state", byStateParams],
    queryFn: () => api.statsByState(byStateParams),
    enabled: !search.state,
  });

  const top = useQuery({
    queryKey: ["stats", "top-employers", search, 20],
    queryFn: () => api.statsTopEmployers({ ...search, limit: 20 }),
  });

  const industriesQuery = useQuery({
    queryKey: ["stats", "industries"],
    queryFn: () => api.statsIndustries(),
  });

  const handleFilterChange = (next: FilterValues) => {
    navigate({ search: () => ({ ...next, employer: undefined }) });
  };

  const { data: monthData, hasProjection } = withProjectionSeries(
    (byMonth.data ?? []).map((r) => ({
      ...r,
      period: r.month,
      label: fmtMonth(r.month),
    })),
  );

  // The indicator cards below plot onto these exact periods so their x-axes
  // line up with the chart above. Taken from the raw response rather than
  // monthData, whose projection padding adds no real month.
  const indicatorPeriods = (byMonth.data ?? []).map((r) => r.month);

  // Headline figures for the window and filters in force.
  const months = byMonth.data ?? [];
  const sumNotices = months.reduce((a, r) => a + r.notice_count, 0);
  const sumWorkers = months.reduce((a, r) => a + r.layoff_total, 0);
  const peak = months.reduce<(typeof months)[number] | null>(
    (best, r) => (!best || r.layoff_total > best.layoff_total ? r : best),
    null,
  );

  return (
    <div className="space-y-6">
      <PageHeader
        kicker="Trends"
        title={search.state ? `Layoff trends in ${stateName(search.state)}` : "Layoff trends"}
        lede={
          <>
            WARN notices and workers affected over time{" "}
            {search.after ? <>since {fmtDate(search.after)}</> : "across all years"}, set against
            official BLS labour-market data. Narrow by state, industry or closure type below.
          </>
        }
      />
      <FilterBar
        values={urlSearch}
        onChange={handleFilterChange}
        showEmployer={false}
        industries={industriesQuery.data}
        defaultDays={DEFAULT_DAYS}
      />
      <ActiveFilters
        values={urlSearch}
        industries={industriesQuery.data}
        onChange={handleFilterChange}
      />

      <Figures>
        <Figure label="Workers affected" value={byMonth.data ? fmtNum(sumWorkers) : null} accent />
        <Figure label="Notices" value={byMonth.data ? fmtNum(sumNotices) : null} />
        {/* Per month, not per notice: notices from count-less sources (OK)
            would drag a per-notice average down. */}
        <Figure
          label="Workers per month"
          value={byMonth.data ? (months.length ? fmtNum(Math.round(sumWorkers / months.length)) : "—") : null}
        />
        <Figure
          label="Peak month"
          value={byMonth.data ? (peak ? fmtMonth(peak.month) : "—") : null}
          note={peak ? `${fmtNum(peak.layoff_total)} workers` : undefined}
        />
      </Figures>

      <ChartCard title="Notices and layoffs by month">
        {byMonth.isLoading ? (
          <SkeletonChart height={320} />
        ) : byMonth.isError ? (
          <QueryError message="Error loading the chart." onRetry={() => byMonth.refetch()} />
        ) : (
          <>
            <WarnTimeChart
              rows={monthData}
              bucket="month"
              subject={search.state ? `in ${stateName(search.state)}` : "across the US"}
              bls={{
                options: BLS_LABOUR_MARKET,
                state: search.state,
                after: search.after,
                before: search.before,
              }}
            />
            {hasProjection && (
              <ProjectionNote
                periodLabel={monthData[monthData.length - 1].label}
              />
            )}
          </>
        )}
      </ChartCard>

      {/* Absolute BLS levels on the same period span as the chart above; the
          overlay itself is the chart's Compare mode. Both follow the state
          filter. */}
      <BlsLevels>
        <IndicatorChart
          dataset="unemployment"
          state={search.state}
          bucket="month"
          after={search.after}
          before={search.before}
          periods={indicatorPeriods}
        />
        <IndicatorChart
          dataset="jolts"
          state={search.state}
          bucket="month"
          after={search.after}
          before={search.before}
          periods={indicatorPeriods}
        />
      </BlsLevels>

      {!search.state && (
        <ChartCard title="By state">
          {byState.isLoading ? (
            <SkeletonChart height={300} />
          ) : byState.isError ? (
            <QueryError message="Error loading the chart." onRetry={() => byState.refetch()} />
          ) : (
            <div role="img" aria-label="Bar chart of workers affected by state">
              <ResponsiveContainer
                width="100%"
                height={Math.max(300, (byState.data?.length ?? 0) * 24)}
              >
                <BarChart
                  layout="vertical"
                  data={(byState.data ?? []).slice().sort((a, b) => b.layoff_total - a.layoff_total)}
                  margin={{ left: 10 }}
                >
                  <CartesianGrid stroke={chart.grid} />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 12, fill: chart.axis }}
                    tickFormatter={fmtCompact}
                  />
                  <YAxis
                    dataKey="state"
                    type="category"
                    tick={{ fontSize: 12, fill: chart.axis }}
                    width={40}
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
        </ChartCard>
      )}

      <CountyImpact
        title="Hardest-hit counties"
        query={{
          state: search.state,
          closure_category: search.closure_category,
          industry: search.industry,
          subsector: search.subsector,
          after: search.after,
          before: search.before,
        }}
      />

      <ChartCard title="Top 20 employers">
        {top.isLoading ? (
          <SkeletonRows rows={8} />
        ) : top.isError ? (
          <QueryError message="Error loading top employers." onRetry={() => top.refetch()} />
        ) : (
          <EmployerRanking rows={top.data ?? []} />
        )}
      </ChartCard>
    </div>
  );
}


function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="card">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {children}
    </div>
  );
}
