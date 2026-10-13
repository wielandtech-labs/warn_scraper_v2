import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { ApiError, api } from "../api/client";
import { BlsLevels } from "../components/BlsLevels";
import { Collapsed } from "../components/Collapsed";
import { EmployerRanking } from "../components/EmployerRanking";
import { Figure, Figures } from "../components/Figures";
import { IndicatorChart } from "../components/IndicatorChart";
import { NoticeMap } from "../components/NoticeMap";
import { PageHeader } from "../components/PageHeader";
import { ProjectionNote } from "../components/ProjectionNote";
import { QueryError } from "../components/QueryError";
import { ReportMarkdown } from "../components/ReportMarkdown";
import { SkeletonBlock, SkeletonChart, SkeletonRows } from "../components/Skeleton";
import { WarnTimeChart } from "../components/WarnTimeChart";
import {
  TimeRangeToggle,
  toRangeQuery,
  type TimeRange,
} from "../components/TimeRangeToggle";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { BLS_PAYROLLS } from "../lib/blsSeries";
import { fmtDate, fmtNum, fmtPeriod } from "../lib/format";
import { withProjectionSeries } from "../lib/projection";
import { deltaCell } from "../lib/scorecard";
import { GradeTile } from "./reports";

export function IndustryReportPage() {
  const { sector } = useParams({ from: "/reports/industry/$sector" });

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
  const topEmployers = useQuery({
    queryKey: ["stats", "top-employers", { industry: sector, after }, 8],
    queryFn: () => api.statsTopEmployers({ industry: sector, after, limit: 8 }),
    enabled: vouched,
  });
  // Periods the payroll card plots onto, so its x-axis matches the chart
  // above it.
  const indicatorPeriods = (overTime.data ?? []).map((r) => r.period);

  const name = card?.sector_name ?? `NAICS ${sector}`;
  useDocumentTitle(
    missing
      ? "Scorecard not found — WARN Index"
      : `${name} layoff scorecard — WARN Index`,
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
      <Link to="/reports" className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
        ← All industry scorecards
      </Link>
      <PageHeader
        kicker={`NAICS ${sector} · weekly scorecard`}
        title={
          <span className="flex items-center gap-4">
            {card && <GradeTile grade={card.grade} />}
            <span className="min-w-0">{name}</span>
          </span>
        }
        lede="Chart, map and employers cover only notices matched to a NAICS code — a partial, unevenly-distributed subset; treat them as directional."
        aside={<TimeRangeToggle value={range} onChange={setRange} />}
      />

      {card && (
        <Figures>
          <Figure
            label="Score"
            value={card.score === null ? "—" : `${Math.round(card.score)}/100`}
            note="higher = healthier"
          />
          <Figure label="Workers, last 90 days" value={fmtNum(card.cur_layoffs)} accent />
          <Figure label="Notices, last 90 days" value={fmtNum(card.cur_notices)} />
          <Figure
            label="vs prior 90 days"
            value={deltaCell(card)}
            note={`${fmtNum(card.prior_layoffs)} workers before`}
          />
        </Figures>
      )}
      {card && (
        <p className="-mt-3 text-xs text-slate-500 dark:text-slate-400">
          Scorecard computed {fmtDate(card.generated_at)}. The written analysis below carries its
          own generation date and can lag these figures by a few days.
        </p>
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
              <WarnTimeChart
                rows={timeData}
                bucket={bucket}
                subject={`in ${name}`}
                bls={{ options: [BLS_PAYROLLS], industry: sector, after }}
              />
              {hasProjection && (
                <ProjectionNote periodLabel={timeData[timeData.length - 1].label} />
              )}
            </>
          )}
        </div>
      )}

      {/* How many jobs the sector holds nationally, for scale: a thousand-job
          notice reads very differently against a sector of 300 thousand than
          against one of twelve million. */}
      {vouched && bucket !== "day" && (
        <BlsLevels>
          <IndicatorChart
            dataset="payrolls"
            industry={sector}
            bucket={bucket}
            after={after}
            periods={indicatorPeriods}
          />
        </BlsLevels>
      )}

      {vouched && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="card lg:col-span-3">
            <h2 className="mb-3 text-lg font-semibold">Where this sector is shedding jobs</h2>
            <NoticeMap industry={sector} after={after} />
          </div>
          <section className="card lg:col-span-2">
            <h2 className="mb-1 text-lg font-semibold">Top employers</h2>
            {topEmployers.isLoading && <SkeletonRows rows={5} />}
            {topEmployers.isError && (
              <QueryError message="Error loading top employers." onRetry={() => topEmployers.refetch()} />
            )}
            {topEmployers.data?.length === 0 && (
              <div className="py-4 text-sm text-slate-500 dark:text-slate-400">No data for this period.</div>
            )}
            {topEmployers.data && topEmployers.data.length > 0 && (
              <EmployerRanking rows={topEmployers.data} />
            )}
          </section>
        </div>
      )}

      <div className="card">
        <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-brand">
          Weekly analysis
        </p>
        <h2 className="mb-3 mt-1 text-lg font-semibold">{name} scorecard</h2>
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
          <Collapsed label="Read the full scorecard">
            <ReportMarkdown markdown={report.data} skipH1 />
          </Collapsed>
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
