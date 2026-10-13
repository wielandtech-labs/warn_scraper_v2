import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import { useTheme } from "../hooks/useTheme";
import { spansOnAxis } from "../lib/annotations";
import type { BlsOption } from "../lib/blsSeries";
import { fmtCompact, fmtNum } from "../lib/format";
import { rebasePair } from "../lib/rebase";
import { CHART_COLORS } from "../lib/themeColors";
import { ProjectionTooltip } from "./ProjectionTooltip";
import { QueryError } from "./QueryError";
import type { Bucket } from "./TimeRangeToggle";

/* The one WARN time-series chart, shared by the dashboard, state pages, the
   Trends page and industry scorecards.

   ONE y-axis, always. Notices and workers affected differ by ~100x, so the
   old two-axis version let the eye compare lines whose relative height was an
   artefact of two arbitrary scales. Instead a toggle picks the measure, and
   "Compare" puts WARN and an official BLS series on a shared index
   (lib/rebase.ts) -- an honest overlay where crossings and divergence mean
   something. US recessions are shaded behind every mode. */

export interface WarnRow {
  period: string;
  label: string;
  notice_count: number | null;
  layoff_total: number | null;
  projected_notice_count?: number | null;
  projected_layoff_total?: number | null;
  forecast_notice_count?: number | null;
  forecast_layoff_total?: number | null;
  forecast_layoff_band?: [number, number] | null;
  actual_notice_count?: number;
  actual_layoff_total?: number;
}

type Mode = "layoffs" | "notices" | "compare";

interface Props {
  rows: WarnRow[];
  bucket: Bucket;
  /** "in Ohio" etc., for the accessible label. */
  subject?: string;
  height?: number;
  /** false where the source publishes no employee counts. */
  hasCounts?: boolean;
  /** BLS series offered in Compare mode; omit to hide the mode. */
  bls?: {
    options: BlsOption[];
    state?: string;
    industry?: string;
    after?: string;
    before?: string;
  };
}

const prefersReducedMotion =
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function WarnTimeChart({
  rows,
  bucket,
  subject = "",
  height = 300,
  hasCounts = true,
  bls,
}: Props) {
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];
  const [mode, setMode] = useState<Mode>(hasCounts ? "layoffs" : "notices");
  const [blsIndex, setBlsIndex] = useState(0);

  // BLS is monthly, so there is nothing to compare on a daily axis.
  const canCompare = !!bls && bls.options.length > 0 && bucket !== "day";
  const active: Mode = mode === "compare" && !canCompare ? (hasCounts ? "layoffs" : "notices") : mode;
  const option = canCompare ? bls.options[Math.min(blsIndex, bls.options.length - 1)] : null;

  // Same key as IndicatorChart, so the BLS-levels cards reuse this fetch.
  const indicators = useQuery({
    queryKey: [
      "stats",
      "indicators",
      {
        dataset: option?.dataset,
        state: bls?.state,
        industry: bls?.industry,
        bucket,
        after: bls?.after,
        before: bls?.before,
      },
    ],
    queryFn: () =>
      api.statsIndicators({
        dataset: option!.dataset,
        state: bls?.state,
        industry: bls?.industry,
        bucket: bucket as "month" | "year",
        after: bls?.after,
        before: bls?.before,
      }),
    enabled: active === "compare" && !!option,
  });

  const recessions = spansOnAxis(rows, (r) => r.label);
  // Long series animate slowly and gain nothing from it.
  const animate = !prefersReducedMotion && rows.length <= 60;

  const modes: { id: Mode; label: string }[] = [
    ...(hasCounts ? [{ id: "layoffs" as const, label: "Workers affected" }] : []),
    { id: "notices", label: "Notices" },
    ...(canCompare ? [{ id: "compare" as const, label: "Compare with BLS" }] : []),
  ];

  const controls = (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div
        role="radiogroup"
        aria-label="Chart measure"
        className="inline-flex rounded-full border border-slate-200 bg-slate-50 p-0.5 dark:border-slate-800 dark:bg-slate-950"
      >
        {modes.map((m) => (
          <button
            key={m.id}
            type="button"
            role="radio"
            aria-checked={active === m.id}
            onClick={() => setMode(m.id)}
            className={
              "rounded-full px-3 py-1 text-xs font-medium transition-colors " +
              (active === m.id
                ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100")
            }
          >
            {m.label}
          </button>
        ))}
      </div>
      {active === "compare" && bls && bls.options.length > 1 && (
        <select
          aria-label="BLS series"
          value={blsIndex}
          onChange={(e) => setBlsIndex(Number(e.target.value))}
          className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs dark:border-slate-700 dark:bg-slate-900"
        >
          {bls.options.map((o, i) => (
            <option key={o.key + o.dataset} value={i}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </div>
  );

  // A span inside one period (a 2020 recession on a yearly axis) has x1 ===
  // x2, which a point-scale ReferenceArea draws zero-wide -- use a wide
  // translucent rule instead.
  const shading = recessions.map((s) => {
    const label = { value: s.label, position: "insideTopLeft" as const, fontSize: 10, fill: chart.axis };
    return s.x1 === s.x2 ? (
      <ReferenceLine key={s.label} x={s.x1} stroke={chart.annotation} strokeWidth={14} label={label} />
    ) : (
      <ReferenceArea
        key={s.label}
        x1={s.x1}
        x2={s.x2}
        fill={chart.annotation}
        stroke="none"
        label={label}
      />
    );
  });
  const shadingNote =
    recessions.length > 0 ? "Shaded: US recessions (NBER). " : "";

  if (active === "compare" && option) {
    if (indicators.isError) {
      return (
        <>
          {controls}
          <QueryError message="Error loading the BLS series." onRetry={() => indicators.refetch()} />
        </>
      );
    }
    const blsByPeriod = new Map(
      (indicators.data ?? []).map((r) => [r.period, r.values[option.key]]),
    );
    // Complete periods only: a partial current period (projected/forecast
    // row, flagged by actual_*) would read as a collapse on an index, and
    // forecast-only months (null actuals) would stretch the axis.
    const warnKey = hasCounts ? "layoff_total" : "notice_count";
    const complete = rows.filter(
      (r) =>
        r.notice_count != null &&
        r.actual_layoff_total === undefined &&
        r.actual_notice_count === undefined,
    );
    const warnRaw = complete.map((r) => r[warnKey]);
    const blsRaw = complete.map((r) => blsByPeriod.get(r.period));
    const { a: warnIdx, b: blsIdx } = rebasePair(warnRaw, blsRaw);
    const data = complete.map((r, i) => ({
      period: r.period,
      label: r.label,
      warn: warnIdx[i],
      bls: blsIdx[i],
      warnRaw: warnRaw[i],
      blsRaw: blsRaw[i],
    }));
    const warnLabel = hasCounts ? "Workers affected (WARN)" : "Notices (WARN)";
    return (
      <>
        {controls}
        <div
          role="img"
          aria-label={`Indexed line chart comparing WARN ${hasCounts ? "workers affected" : "notices"} ${subject} with ${option.label}`}
        >
          <ResponsiveContainer width="100%" height={height}>
            <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={chart.grid} />
              {shading}
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: chart.axis }} minTickGap={24} />
              <YAxis
                tick={{ fontSize: 12, fill: chart.axis }}
                width={44}
                domain={[0, "auto"]}
                tickFormatter={(v: number) => String(Math.round(v))}
              />
              <ReferenceLine y={100} stroke={chart.axis} strokeDasharray="4 4" strokeOpacity={0.6} />
              <Tooltip
                contentStyle={chart.tooltip}
                labelStyle={chart.tooltipLabel}
                formatter={(value, name, item) => {
                  const row = item.payload as (typeof data)[number];
                  const raw =
                    name === option.label
                      ? row.blsRaw != null
                        ? option.format(row.blsRaw)
                        : "—"
                      : fmtNum(row.warnRaw);
                  return [`${Math.round(Number(value))} (${raw})`, name];
                }}
              />
              <Line
                type="monotone"
                dataKey="warn"
                name={warnLabel}
                stroke={chart.layoffs}
                strokeWidth={2}
                dot={false}
                isAnimationActive={animate}
              />
              <Line
                type="monotone"
                dataKey="bls"
                name={option.label}
                stroke={chart.context}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={animate}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        {/* Direct legend: both series named in ink, keyed by a swatch. */}
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
          <LegendKey color={chart.layoffs} label={warnLabel} />
          <LegendKey color={chart.context} label={`${option.label} (BLS)`} />
        </div>
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          {indicators.isLoading
            ? "Loading BLS series… "
            : "Each line is scaled so its average over the periods both cover = 100; hover for actual values. "}
          {shadingNote}
          {bucket === "year" ? "BLS values are monthly averages by year." : ""}
        </p>
      </>
    );
  }

  const isLayoffs = active === "layoffs";
  const color = isLayoffs ? chart.layoffs : chart.notices;
  const name = isLayoffs ? "Workers affected" : "Notices";
  const key = isLayoffs ? "layoff_total" : "notice_count";
  return (
    <>
      {controls}
      <div role="img" aria-label={`Line chart of ${name.toLowerCase()} ${subject} over time`}>
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={chart.grid} />
            {shading}
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: chart.axis }} minTickGap={24} />
            <YAxis tick={{ fontSize: 12, fill: chart.axis }} tickFormatter={fmtCompact} width={44} />
            <Tooltip
              content={<ProjectionTooltip />}
              contentStyle={chart.tooltip}
              labelStyle={chart.tooltipLabel}
            />
            {/* 80% forecast interval -- workers affected only (the model's
                band is for that series). All-null when no forecast. */}
            {isLayoffs && (
              <Area
                type="monotone"
                dataKey="forecast_layoff_band"
                name="Workers affected (forecast range)"
                fill={chart.layoffs}
                fillOpacity={0.12}
                stroke="none"
                legendType="none"
                isAnimationActive={false}
              />
            )}
            {/* Soft fill under the actuals gives the single series some body. */}
            <Area
              type="monotone"
              dataKey={key}
              name={name}
              stroke={color}
              strokeWidth={2}
              fill={color}
              fillOpacity={0.08}
              dot={false}
              isAnimationActive={animate}
            />
            {/* Dashed pace projection / forecast for the current period on;
                all-null (invisible) when inactive. Drawn after the actuals. */}
            <Line
              type="monotone"
              dataKey={`projected_${key}`}
              name={`${name} (projected)`}
              stroke={color}
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={false}
              legendType="none"
              animationBegin={animate ? 1500 : 0}
              isAnimationActive={animate}
            />
            <Line
              type="monotone"
              dataKey={`forecast_${key}`}
              name={`${name} (forecast)`}
              stroke={color}
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={false}
              legendType="none"
              animationBegin={animate ? 1500 : 0}
              isAnimationActive={animate}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {shadingNote && (
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{shadingNote}</p>
      )}
    </>
  );
}

function LegendKey({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className="h-0.5 w-4 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}
