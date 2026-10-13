import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { api, ApiError } from "../api/client";
import { AlertSignup } from "../components/AlertSignup";
import { BlsLevels } from "../components/BlsLevels";
import { Collapsed } from "../components/Collapsed";
import { CountyImpact } from "../components/CountyImpact";
import { EmployerRanking } from "../components/EmployerRanking";
import { Figure, Figures } from "../components/Figures";
import { ForecastNote } from "../components/ForecastNote";
import { IndicatorChart } from "../components/IndicatorChart";
import { NoticeList } from "../components/NoticeList";
import { NoticeMap } from "../components/NoticeMap";
import { ProjectionNote } from "../components/ProjectionNote";
import { QueryError } from "../components/QueryError";
import { ReportMarkdown } from "../components/ReportMarkdown";
import { SkeletonBlock, SkeletonChart, SkeletonRows } from "../components/Skeleton";
import { StateSilhouette } from "../components/StateSilhouette";
import {
  TimeRangeToggle,
  toRangeQuery,
  type TimeRange,
} from "../components/TimeRangeToggle";
import { UnavailableNotice } from "../components/UnavailableNotice";
import { WarnTimeChart } from "../components/WarnTimeChart";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { BLS_LABOUR_MARKET } from "../lib/blsSeries";
import {
  STATE_NAMES,
  fmtDate,
  fmtNum,
  fmtPeriod,
  fmtRelativeDays,
  stateName,
} from "../lib/format";
import { withForecastSeries } from "../lib/forecast";
import { withProjectionSeries } from "../lib/projection";
import { LAW_BLOCKED, NO_COUNTS } from "../lib/unavailable";

const RANGE_PHRASE: Record<TimeRange, string> = {
  "30d": "in the last 30 days",
  "1y": "in the past year",
  "5y": "in the last five years",
  all: "on record",
};

export function StateDetailPage() {
  const { state } = useParams({ from: "/states/$state" });
  const code = state.toUpperCase();
  const valid = code in STATE_NAMES;
  // State law blocks publication of these states' notices — no data will ever
  // arrive, so skip the stats fetches and show an explainer instead.
  const blocked = code in LAW_BLOCKED;
  // The source publishes notices but no employee counts — layoff totals are
  // structurally unavailable, so show a note instead of a misleading zero.
  const noCounts = code in NO_COUNTS;
  const name = stateName(code);

  useDocumentTitle(
    valid ? `${name} layoffs & WARN notices — WARN Index` : "Unknown state — WARN Index",
  );

  const [range, setRange] = useState<TimeRange>("5y");
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
  // Weekly statistical forecast — a 404 just means this state never cleared
  // the lowest forecast model tier (or the job hasn't run yet); fall back to
  // the pace projection instead of retrying.
  const forecast = useQuery({
    queryKey: ["forecast", code],
    queryFn: () => api.getForecast(code),
    enabled: valid && !blocked && bucket === "month",
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
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
  // Weekly sentiment report — a 404 just means none has been generated yet
  // (new deploy, fresh volume), so don't retry it and hide the card instead.
  const report = useQuery({
    queryKey: ["report", code],
    queryFn: () => api.getReport(code),
    enabled: valid && !blocked,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  });
  const reportMissing =
    report.isError && report.error instanceof ApiError && report.error.status === 404;

  if (!valid) {
    return (
      <div className="card text-center">
        <p className="text-slate-700 dark:text-slate-300">Unknown state code “{state}”.</p>
        <Link to="/states" className="mt-2 inline-block text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
          ← Browse all states
        </Link>
      </div>
    );
  }

  if (blocked) {
    return (
      <div className="space-y-6">
        <div>
          <Link to="/states" className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
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
  // Periods the indicator cards plot onto, so their x-axes match the chart
  // above — including its forecast months, which the cards leave blank.
  const indicatorPeriods = timeData.map((r) => r.period);
  // Rank among reporting states over the same window -- by notices where the
  // source publishes no worker counts.
  const ranked = (byState.data ?? [])
    .filter((s) => s.notice_count > 0)
    .sort((a, b) =>
      noCounts ? b.notice_count - a.notice_count : b.layoff_total - a.layoff_total,
    );
  const rank = noticeCount > 0 ? ranked.findIndex((s) => s.state === code) + 1 : 0;
  const latest = recent.data?.items[0]?.notice_date;

  return (
    <div className="space-y-6">
      <Link to="/states" className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
        ← All states
      </Link>
      <header className="relative flex flex-col gap-4 overflow-hidden border-b border-slate-200 pb-5 sm:flex-row sm:items-end sm:justify-between dark:border-slate-800">
        {/* The state's own outline as the page's editorial art. */}
        <StateSilhouette
          code={code}
          size={168}
          className="pointer-events-none absolute -right-4 -top-6 hidden text-brand/[0.07] md:block dark:text-brand/[0.12]"
        />
        <div className="relative flex min-w-0 items-center gap-4">
          <StateSilhouette code={code} size={56} className="shrink-0 text-brand" />
          <div className="min-w-0">
            <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-brand">
              WARN notices · {code}
            </p>
            <h1 className="mt-1 text-3xl font-semibold leading-tight text-slate-900 dark:text-slate-50">
              {name}
            </h1>
            <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-600 dark:text-slate-400">
              {byState.data
                ? noCounts
                  ? `${fmtNum(noticeCount)} layoff and closure notices filed ${RANGE_PHRASE[range]}.`
                  : `${fmtNum(layoffTotal)} workers affected across ${fmtNum(noticeCount)} notices filed ${RANGE_PHRASE[range]}.`
                : "Layoff and closure notices filed under the WARN Act."}
            </p>
          </div>
        </div>
        <div className="relative flex flex-wrap items-center gap-3 text-sm">
          <TimeRangeToggle value={range} onChange={setRange} />
          <Link
            to="/map"
            search={{ state: code }}
            className="font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            Map →
          </Link>
          <a
            href={`/states/${code}/feed.rss`}
            className="font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            RSS
          </a>
        </div>
      </header>

      <Figures>
        <Figure
          label="Workers affected"
          value={byState.data ? (noCounts ? "—" : fmtNum(layoffTotal)) : null}
          note={noCounts ? "Not published by the source" : undefined}
          accent
        />
        <Figure label="Notices" value={byState.data ? fmtNum(noticeCount) : null} />
        <Figure
          label="Rank among states"
          value={byState.data ? (rank ? `#${rank}` : "—") : null}
          note={rank ? `of ${ranked.length}, by ${noCounts ? "notices" : "workers"}` : undefined}
        />
        <Figure
          label="Latest notice"
          value={recent.data ? fmtDate(latest) : null}
          note={fmtRelativeDays(latest) ?? undefined}
        />
      </Figures>

      {noCounts && (
        <p className="text-sm text-slate-500 dark:text-slate-400">{NO_COUNTS[code]}</p>
      )}

      <div className="card">
        <h2 className="mb-3 text-lg font-semibold">Notices and layoffs over time</h2>
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
              hasCounts={!noCounts}
              bls={{ options: BLS_LABOUR_MARKET, state: code, after }}
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

      {/* How this state's labour market was doing over the same span, as
          absolute levels (the overlay is the chart's Compare mode). Skipped
          on the 30-day range: every BLS series here is monthly, so there is
          nothing to plot against a daily axis. */}
      {bucket !== "day" && (
        <BlsLevels>
          <IndicatorChart
            dataset="unemployment"
            state={code}
            bucket={bucket}
            after={after}
            periods={indicatorPeriods}
          />
          <IndicatorChart
            dataset="jolts"
            state={code}
            bucket={bucket}
            after={after}
            periods={indicatorPeriods}
          />
        </BlsLevels>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="card">
          <h2 className="mb-1 text-lg font-semibold">Top employers</h2>
          {topEmployers.isLoading && <SkeletonRows rows={5} />}
          {topEmployers.isError && (
            <QueryError message="Error loading top employers." onRetry={() => topEmployers.refetch()} />
          )}
          {topEmployers.data?.length === 0 && (
            <div className="py-4 text-sm text-slate-500 dark:text-slate-400">No data yet.</div>
          )}
          {topEmployers.data && topEmployers.data.length > 0 && (
            <EmployerRanking rows={topEmployers.data} />
          )}
        </section>

        <section className="card p-0">
          <div className="flex items-center justify-between px-5 pb-1 pt-5">
            <h2 className="text-lg font-semibold">Latest filings</h2>
            <Link
              to="/notices"
              search={{ state: code }}
              className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
            >
              View all →
            </Link>
          </div>
          {recent.isLoading && <SkeletonRows rows={5} />}
          {recent.isError && (
            <QueryError message="Error loading notices." onRetry={() => recent.refetch()} />
          )}
          {recent.data?.items.length === 0 && (
            <div className="px-5 py-4 text-sm text-slate-500 dark:text-slate-400">No notices yet.</div>
          )}
          {recent.data && <NoticeList notices={recent.data.items} lead="employer" />}
        </section>
      </div>

      <div className="card">
        <h2 className="mb-3 text-lg font-semibold">Layoffs across {name}</h2>
        <NoticeMap state={code} after={after} />
      </div>

      <CountyImpact
        title={`Hardest-hit counties in ${name}`}
        query={{ state: code, after, limit: 10 }}
      />

      {!reportMissing && (
        <div className="card">
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-brand">
            Weekly analysis
          </p>
          <h2 className="mb-3 mt-1 text-lg font-semibold">{name} economic outlook</h2>
          {report.isLoading ? (
            <div className="space-y-2">
              <SkeletonBlock className="h-4 w-1/3" />
              <SkeletonBlock className="h-24 w-full" />
              <SkeletonBlock className="h-4 w-2/3" />
            </div>
          ) : report.isError ? (
            <QueryError
              message="Error loading the sentiment report."
              onRetry={() => report.refetch()}
            />
          ) : report.data ? (
            <Collapsed label="Read the full outlook">
              <ReportMarkdown markdown={report.data} skipH1 />
            </Collapsed>
          ) : null}
        </div>
      )}

      <AlertSignup state={code} />
    </div>
  );
}
