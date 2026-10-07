import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useTheme } from "../hooks/useTheme";
import { CHART_COLORS } from "../lib/themeColors";

/* A "t-bar" chart: one horizontal bar per row, its length the test statistic
   (estimate / standard error), with dashed reference lines at ±1.96 — a bar
   past a line is individually significant at 5%. Polarity is the encoding:
   a significant rise in layoff activity (bad news) takes the layoffs red, a
   significant easing the notices sky, and anything that misses the caller's
   gate (a multiple-testing q-value, or |z| for shrunk estimates) stays
   neutral gray. Reuses the site's validated
   notices/layoffs pair rather than introducing new hues. Identity never
   rides on color alone: the tooltip and the table below spell out every
   number and verdict. */

export interface TBarRow {
  code: string;
  name: string;
  stat: number; // t (or shrunk z)
  effect: string; // pre-formatted effect, e.g. "+43%/yr"
  ci: string; // pre-formatted 95% CI
  q: number | null;
  significant: boolean;
}

const NEUTRAL = { light: "#cbd5e1", dark: "#475569" }; // slate-300 / slate-600

function verdict(row: TBarRow): string {
  if (!row.significant) return "not significant";
  return row.stat > 0 ? "significant rise" : "significant easing";
}

function TBarTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: TBarRow }[];
}) {
  const { resolved } = useTheme();
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const chart = CHART_COLORS[resolved];
  return (
    <div className="rounded-md px-3 py-2 text-xs shadow-sm" style={chart.tooltip}>
      <div className="font-semibold">{row.name}</div>
      <div>
        {row.effect} <span className="opacity-70">(95% CI {row.ci})</span>
      </div>
      <div className="tabular-nums">
        t = {row.stat.toFixed(2)}
        {row.q !== null && <> · q = {row.q.toFixed(3)}</>}
      </div>
      <div className="opacity-70">{verdict(row)}</div>
    </div>
  );
}

export function TBarChart({
  rows,
  label,
  statLabel = "t-statistic",
}: {
  rows: TBarRow[];
  label: string;
  statLabel?: string;
}) {
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];
  const data = rows.slice().sort((a, b) => b.stat - a.stat);
  const extent = Math.max(2.5, ...data.map((r) => Math.abs(r.stat))) * 1.05;
  const fill = (row: TBarRow) =>
    !row.significant
      ? NEUTRAL[resolved]
      : row.stat > 0
        ? chart.layoffs
        : chart.notices;

  return (
    <div>
      <div role="img" aria-label={label}>
        <ResponsiveContainer width="100%" height={Math.max(160, data.length * 22 + 40)}>
          <BarChart layout="vertical" data={data} margin={{ left: 10, right: 16 }} barCategoryGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} horizontal={false} />
            <XAxis
              type="number"
              domain={[-extent, extent]}
              tick={{ fontSize: 12, fill: chart.axis }}
              tickFormatter={(v: number) => v.toFixed(0)}
              label={{ value: statLabel, position: "insideBottom", offset: -2, fontSize: 12, fill: chart.axis }}
              height={36}
            />
            <YAxis
              dataKey="code"
              type="category"
              tick={{ fontSize: 12, fill: chart.axis }}
              width={48}
              interval={0}
            />
            <ReferenceLine x={0} stroke={chart.axis} />
            <ReferenceLine x={1.96} stroke={chart.axis} strokeDasharray="4 4" />
            <ReferenceLine x={-1.96} stroke={chart.axis} strokeDasharray="4 4" />
            <Tooltip content={<TBarTooltip />} cursor={{ fill: chart.cursor }} />
            <Bar dataKey="stat" isAnimationActive={false}>
              {data.map((row) => (
                <Cell key={row.code} fill={fill(row)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-slate-500 dark:text-slate-400">Show table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="min-w-full text-left text-xs">
            <thead className="text-slate-500 dark:text-slate-400">
              <tr>
                <th className="py-1 pr-3">Name</th>
                <th className="py-1 pr-3">Effect</th>
                <th className="py-1 pr-3">95% CI</th>
                <th className="py-1 pr-3">{statLabel}</th>
                <th className="py-1 pr-3">q</th>
                <th className="py-1">Verdict</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {data.map((row) => (
                <tr key={row.code} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-1 pr-3">{row.name}</td>
                  <td className="py-1 pr-3">{row.effect}</td>
                  <td className="py-1 pr-3">{row.ci}</td>
                  <td className="py-1 pr-3">{row.stat.toFixed(2)}</td>
                  <td className="py-1 pr-3">{row.q === null ? "—" : row.q.toFixed(3)}</td>
                  <td className="py-1">{verdict(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
