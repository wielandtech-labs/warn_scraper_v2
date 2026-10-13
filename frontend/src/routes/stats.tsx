import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
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
import { CompanyLogo } from "../components/CompanyLogo";
import { CountyImpact } from "../components/CountyImpact";
import { IndicatorChart } from "../components/IndicatorChart";
import { FilterBar, type FilterValues, resolveAfter } from "../components/FilterBar";
import { PageHeader } from "../components/PageHeader";
import { Peek } from "../components/Peek";
import { CompanyPeek } from "../components/peeks";
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
  const topMax = Math.max(1, ...(top.data ?? []).map((e) => e.layoff_total));

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

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-4 dark:border-slate-800 dark:bg-slate-800">
        <Figure label="Workers affected" value={byMonth.data ? fmtNum(sumWorkers) : null} accent />
        <Figure label="Notices" value={byMonth.data ? fmtNum(sumNotices) : null} />
        <Figure
          label="Avg. per notice"
          value={byMonth.data ? (sumNotices ? fmtNum(Math.round(sumWorkers / sumNotices)) : "—") : null}
        />
        <Figure
          label="Peak month"
          value={byMonth.data ? (peak ? fmtMonth(peak.month) : "—") : null}
          note={peak ? `${fmtNum(peak.layoff_total)} workers` : undefined}
        />
      </dl>

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
          <ol className="divide-y divide-slate-100 dark:divide-slate-800">
            {(top.data ?? []).map((e, i) => (
              <li key={e.employer} className="flex items-center gap-3 py-2.5">
                <span className="w-6 shrink-0 text-right font-display text-sm text-slate-400 tabular-nums">
                  {i + 1}
                </span>
                <CompanyLogo name={e.employer} companyId={e.company_id} size={28} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {e.company_id ? (
                      <Peek content={() => <CompanyPeek id={e.company_id!} name={e.employer} />}>
                        <Link
                          to="/companies/$companyId"
                          params={{ companyId: String(e.company_id) }}
                          className="text-slate-900 hover:text-sky-700 hover:underline dark:text-slate-100 dark:hover:text-sky-400"
                        >
                          {e.employer}
                        </Link>
                      </Peek>
                    ) : (
                      e.employer
                    )}
                  </div>
                  <div aria-hidden className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${(e.layoff_total / topMax) * 100}%`, backgroundColor: chart.layoffs }}
                    />
                  </div>
                </div>
                <div className="w-28 shrink-0 text-right">
                  <div className="text-sm font-semibold tabular-nums">{fmtNum(e.layoff_total)}</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {e.notice_count} {e.notice_count === 1 ? "notice" : "notices"}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </ChartCard>
    </div>
  );
}

function Figure({
  label,
  value,
  note,
  accent = false,
}: {
  label: string;
  value: string | null;
  note?: string;
  accent?: boolean;
}) {
  return (
    <div className="bg-white p-4 dark:bg-slate-900">
      <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
        {label}
      </dt>
      <dd
        className={`mt-1 font-display text-2xl font-semibold tabular-nums ${accent ? "text-brand dark:text-brand-dark" : "text-slate-900 dark:text-slate-50"}`}
      >
        {value ?? <span className="inline-block h-7 w-20 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />}
      </dd>
      {note && <div className="text-xs text-slate-500 dark:text-slate-400">{note}</div>}
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
