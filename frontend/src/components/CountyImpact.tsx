import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
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
import type { CountyImpactStat } from "../api/types";
import { useTheme } from "../hooks/useTheme";
import { fmtNum } from "../lib/format";
import { CHART_COLORS } from "../lib/themeColors";
import { DataTable } from "./DataTable";
import { QueryError } from "./QueryError";
import { SkeletonChart } from "./Skeleton";

export interface CountyImpactQuery {
  state?: string;
  closure_category?: string;
  industry?: string;
  subsector?: string;
  after?: string;
  before?: string;
  limit?: number;
}

const CHART_ROWS = 15;

const fmtPct = (v: number) => `${v.toFixed(2)}%`;

const columns: ColumnDef<CountyImpactStat, unknown>[] = [
  {
    header: "County",
    accessorKey: "county",
    cell: (info) => (
      <span className="font-medium">
        {info.row.original.county}, {info.row.original.state}
      </span>
    ),
  },
  {
    header: "Layoffs",
    accessorKey: "layoff_total",
    cell: (info) => fmtNum(info.getValue() as number),
  },
  {
    header: "County employment",
    accessorKey: "employment_base",
    cell: (info) => fmtNum(info.getValue() as number),
  },
  {
    header: "% of employment",
    accessorKey: "impact_pct",
    cell: (info) => fmtPct(info.getValue() as number),
  },
];

/** Counties ranked by layoffs as a share of their CBP employment base. */
export function CountyImpact({
  title,
  query,
}: {
  title: string;
  query: CountyImpactQuery;
}) {
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];

  const impact = useQuery({
    queryKey: ["stats", "county-impact", query],
    queryFn: () => api.statsCountyImpact(query),
  });

  const rows = impact.data ?? [];
  const chartRows = rows.slice(0, CHART_ROWS).map((r) => ({
    ...r,
    label: `${r.county}, ${r.state}`,
  }));
  const cbpYear = rows[0]?.cbp_year;

  return (
    <div className="card">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {impact.isLoading ? (
        <SkeletonChart height={320} />
      ) : impact.isError ? (
        <QueryError message="Error loading the chart." onRetry={() => impact.refetch()} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No counties with enough reported layoffs match these filters.
        </p>
      ) : (
        <div className="space-y-4">
          <div
            role="img"
            aria-label="Bar chart of counties by layoffs as a share of county employment"
          >
            <ResponsiveContainer width="100%" height={Math.max(160, chartRows.length * 28)}>
              <BarChart layout="vertical" data={chartRows} margin={{ left: 30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 12, fill: chart.axis }}
                  tickFormatter={fmtPct}
                />
                <YAxis
                  dataKey="label"
                  type="category"
                  tick={{ fontSize: 11, fill: chart.axis }}
                  width={170}
                />
                <Tooltip
                  formatter={(v: number) => fmtPct(v)}
                  contentStyle={chart.tooltip}
                  labelStyle={chart.tooltipLabel}
                  cursor={{ fill: chart.cursor }}
                />
                <Bar dataKey="impact_pct" name="Share of county employment" fill={chart.layoffs} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <DataTable data={rows} columns={columns} />
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Share of {cbpYear ?? "latest"} county employment (Census County Business
            Patterns). Only notices with a reported layoff count are included, so
            shares understate true impact; counties without a CBP match or with
            fewer than 10 reported layoffs are omitted.
          </p>
        </div>
      )}
    </div>
  );
}
