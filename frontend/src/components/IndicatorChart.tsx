import { useQuery } from "@tanstack/react-query";
import {
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
import type { IndicatorDataset } from "../api/types";
import { useTheme } from "../hooks/useTheme";
import { fmtCompact, fmtPeriod } from "../lib/format";
import { CHART_COLORS } from "../lib/themeColors";
import { QueryError } from "./QueryError";
import { SkeletonChart } from "./Skeleton";

/* Official BLS context, rendered as a companion card beneath a WARN time
   series. Deliberately its own chart rather than extra lines on the chart
   above: a rate or a national job count shares no scale with a notice count,
   and a second y-axis is the single most misread thing a chart can do. The
   two charts are tied together by sharing an x-axis domain instead — see
   `periods` below.

   One component serves all three datasets; DATASETS holds everything that
   varies. Adding a BLS dataset means adding a row there and a catalog entry
   on the Python side, not another chart component. */

interface MeasureSpec {
  key: string;
  label: string;
}

interface DatasetSpec {
  title: string;
  measures: MeasureSpec[];
  /** Y-axis tick formatter; also used for tooltip values. */
  format: (v: number) => string;
  /** Sits under the chart — says exactly which BLS program the numbers are. */
  source: string;
}

const DATASETS: Record<IndicatorDataset, DatasetSpec> = {
  unemployment: {
    title: "Unemployment rate",
    measures: [
      { key: "u3", label: "Unemployment rate (U-3)" },
      { key: "u6", label: "Underemployment (U-6)" },
    ],
    format: (v) => `${v}%`,
    source:
      "U.S. Bureau of Labor Statistics, seasonally adjusted. U-3 is the headline " +
      "rate; U-6 adds people working part time because they cannot find full-time " +
      "work, plus those who have given up looking. State rates come from the Local " +
      "Area Unemployment Statistics programme, which publishes no state U-6.",
  },
  jolts: {
    title: "Job turnover",
    measures: [
      { key: "layoffs", label: "Layoffs & discharges" },
      { key: "openings", label: "Job openings" },
      { key: "quits", label: "Quits" },
    ],
    format: (v) => fmtCompact(v * 1000),
    source:
      "U.S. Bureau of Labor Statistics, Job Openings and Labor Turnover Survey, " +
      "seasonally adjusted. These count separations that actually happened across " +
      "the whole economy, so they run far above WARN notices, which only cover " +
      "larger employers announcing in advance. State estimates are modelled and " +
      "published annually, so they end well short of the national series.",
  },
  payrolls: {
    title: "Employment",
    measures: [{ key: "employment", label: "Jobs" }],
    format: (v) => fmtCompact(v * 1000),
    source:
      "U.S. Bureau of Labor Statistics, Current Employment Statistics, all " +
      "employees, seasonally adjusted. Industry figures use the closest BLS " +
      "aggregate, which is broader than the NAICS sector where several sectors " +
      "share one.",
  },
};

interface Props {
  dataset: IndicatorDataset;
  /** Omit for national. */
  state?: string;
  /** NAICS sector id; payrolls only. */
  industry?: string;
  bucket: "month" | "year";
  after?: string;
  before?: string;
  /** Period keys from the chart above, so both x-axes cover the same span. */
  periods: string[];
}

export function IndicatorChart({
  dataset,
  state,
  industry,
  bucket,
  after,
  before,
  periods,
}: Props) {
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];
  const spec = DATASETS[dataset];

  const query = useQuery({
    queryKey: ["stats", "indicators", { dataset, state, industry, bucket, after, before }],
    queryFn: () => api.statsIndicators({ dataset, state, industry, bucket, after, before }),
  });

  const rows = query.data ?? [];

  /* Left-join onto the parent chart's periods so the two x-axes line up
     exactly. Without this the cards drift apart whenever one series starts
     later than the other — which is the normal case, since WARN coverage and
     BLS coverage begin in different years. Periods the indicator doesn't
     reach (state JOLTS stops months short of national) stay undefined, so
     the line simply ends rather than dropping to zero. */
  const byPeriod = new Map(rows.map((r) => [r.period, r.values]));
  const data = periods.map((period) => ({
    period,
    label: fmtPeriod(period, bucket),
    ...(byPeriod.get(period) ?? {}),
  }));

  // Only draw a measure BLS actually publishes here — state pages would
  // otherwise carry a permanently empty U-6 entry in the legend.
  const measures = spec.measures.filter((m) =>
    data.some((row) => typeof (row as Record<string, unknown>)[m.key] === "number"),
  );

  if (query.isLoading) {
    return (
      <div className="card">
        <h2 className="mb-3 text-lg font-semibold">{spec.title}</h2>
        <SkeletonChart height={220} />
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="card">
        <h2 className="mb-3 text-lg font-semibold">{spec.title}</h2>
        <QueryError
          message="Error loading the indicator chart."
          onRetry={() => query.refetch()}
        />
      </div>
    );
  }
  // Nothing to show before the first fetch-bls run, or where BLS publishes
  // nothing for this state or sector. Render no card at all rather than an
  // empty frame.
  if (measures.length === 0) return null;

  return (
    <div className="card">
      <h2 className="mb-3 text-lg font-semibold">{spec.title}</h2>
      <div role="img" aria-label={`Line chart of ${spec.title.toLowerCase()} over time`}>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 12, fill: chart.axis }}
              minTickGap={24}
            />
            {/* One axis: every measure in a dataset shares a unit, which is
                why these are three cards and not three extra lines above. */}
            <YAxis
              tick={{ fontSize: 12, fill: chart.axis }}
              tickFormatter={spec.format}
              width={56}
            />
            <Tooltip
              formatter={(value) => spec.format(Number(value))}
              contentStyle={chart.tooltip}
              labelStyle={chart.tooltipLabel}
            />
            {measures.length > 1 && <Legend />}
            {measures.map((m) => (
              <Line
                key={m.key}
                type="monotone"
                dataKey={m.key}
                name={m.label}
                stroke={chart.indicators[spec.measures.indexOf(m) % chart.indicators.length]}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        {bucket === "year" ? "Monthly average by year. " : ""}
        {spec.source}
      </p>
    </div>
  );
}
