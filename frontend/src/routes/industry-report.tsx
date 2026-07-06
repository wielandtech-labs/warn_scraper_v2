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

import { ApiError, api } from "../api/client";
import { NoticeMap } from "../components/NoticeMap";
import { ProjectionNote } from "../components/ProjectionNote";
import { QueryError } from "../components/QueryError";
import { ReportMarkdown } from "../components/ReportMarkdown";
import { SkeletonBlock, SkeletonChart } from "../components/Skeleton";
import {
  TimeRangeToggle,
  toRangeQuery,
  type TimeRange,
} from "../components/TimeRangeToggle";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useTheme } from "../hooks/useTheme";
import { fmtCompact, fmtPeriod } from "../lib/format";
import { projectionTooltip, withProjectionSeries } from "../lib/projection";
import { CHART_COLORS } from "../lib/themeColors";
import { GradeBadge } from "./reports";

export function IndustryReportPage() {
  const { sector } = useParams({ from: "/reports/industry/$sector" });
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];

  const [range, setRange] = useState<TimeRange>("1y");
  const { after, bucket } = toRangeQuery(range);

  // Usually already cached from the /reports grid; gives us the display name
  // and grade for the header without parsing the markdown.
  const scorecards = useQuery({
    queryKey: ["reports", "industries"],
    queryFn: api.listIndustryScorecards,
  });
  const card = scorecards.data?.find((c) => c.sector === sector);

  const report = useQuery({
    queryKey: ["report", "industry", sector],
    queryFn: () => api.getIndustryReport(sector),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  });
  const missing =
    report.isError && report.error instanceof ApiError && report.error.status === 404;

  // An unknown sector id would pass through the stats API unfiltered (it
  // ignores unrecognized industries) and the map would fetch thousands of
  // national pins, so the chart and map wait until the report fetch has
  // positively vouched for the sector. The report is a fast static-file
  // lookup, so the delay is negligible.
  const vouched = report.isSuccess;
  const overTime = useQuery({
    queryKey: ["stats", "over-time", { industry: sector, after, bucket }],
    queryFn: () => api.statsOverTime({ industry: sector, after, bucket }),
    enabled: vouched,
  });
  const { data: timeData, hasProjection } = withProjectionSeries(
    (overTime.data ?? []).map((r) => ({
      ...r,
      label: fmtPeriod(r.period, bucket),
    })),
  );

  const name = card?.sector_name ?? `NAICS ${sector}`;
  useDocumentTitle(
    missing
      ? "Scorecard not found — WARN Tracker"
      : `${name} layoff scorecard — WARN Tracker`,
  );

  if (missing) {
    return (
      <div className="card text-center">
        <p className="text-slate-700 dark:text-slate-300">No scorecard for “{sector}”.</p>
        <Link
          to="/reports"
          className="mt-2 inline-block text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
        >
          ← All industry scorecards
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to="/reports" className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
          ← All industry scorecards
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{name}</h1>
          {card && <GradeBadge grade={card.grade} />}
        </div>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            NAICS {sector} · weekly national layoff scorecard
          </p>
          <TimeRangeToggle value={range} onChange={setRange} />
        </div>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Chart and map cover only notices matched to a NAICS code — a partial,
          unevenly-distributed subset; treat both as directional.
        </p>
      </div>

      {vouched && (
        <div className="card">
          <h2 className="mb-3 text-lg font-semibold">Where this sector is shedding jobs</h2>
          <NoticeMap industry={sector} after={after} />
        </div>
      )}

      {vouched && (
        <div className="card">
          <h2 className="mb-3 text-lg font-semibold">Job losses over time</h2>
          {overTime.isLoading ? (
            <SkeletonChart height={300} />
          ) : overTime.isError ? (
            <QueryError
              message="Error loading the chart."
              onRetry={() => overTime.refetch()}
            />
          ) : timeData.length === 0 ? (
            <div className="flex h-24 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
              No notices recorded for {name} in this period.
            </div>
          ) : (
            <>
              <div
                role="img"
                aria-label={`Line chart of notice counts and workers affected in ${name} over time`}
              >
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={timeData}>
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
                      formatter={projectionTooltip}
                      contentStyle={chart.tooltip}
                      labelStyle={chart.tooltipLabel}
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
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {hasProjection && (
                <ProjectionNote periodLabel={timeData[timeData.length - 1].label} />
              )}
            </>
          )}
        </div>
      )}

      <div className="card">
        {report.isLoading ? (
          <div className="space-y-2">
            <SkeletonBlock className="h-4 w-1/3" />
            <SkeletonBlock className="h-24 w-full" />
            <SkeletonBlock className="h-4 w-2/3" />
          </div>
        ) : report.isError ? (
          <QueryError
            message="Error loading the scorecard."
            onRetry={() => report.refetch()}
          />
        ) : report.data ? (
          <ReportMarkdown markdown={report.data} skipH1 />
        ) : null}
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        Drill into the underlying notices on the{" "}
        <Link
          to="/notices"
          search={{ industry: sector }}
          className="font-medium text-sky-700 hover:underline dark:text-sky-400"
        >
          notices list
        </Link>{" "}
        filtered to this sector.
      </p>
    </div>
  );
}
