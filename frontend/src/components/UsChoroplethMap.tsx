import { useMemo } from "react";

import { useTheme } from "../hooks/useTheme";
import { fmtCompact, fmtNum } from "../lib/format";
import { CHOROPLETH } from "../lib/themeColors";
import { UsMap } from "./UsMap";

interface StateDatum {
  code: string;
  name: string;
  notice_count: number;
  layoff_total: number;
}

function bucketOf(value: number, thresholds: number[]): number {
  if (value <= 0) return 0;
  for (let i = 0; i < thresholds.length; i++) {
    if (value <= thresholds[i]) return i + 1;
  }
  return thresholds.length + 1;
}

/** US choropleth shaded by layoff totals. */
export function UsChoroplethMap({ data }: { data: StateDatum[] }) {
  const { resolved } = useTheme();
  const ramp = CHOROPLETH[resolved];

  // Quartiles of the nonzero totals: the distribution is heavily skewed
  // toward a few large states, so fixed linear buckets would leave most of
  // the country in the lowest one.
  const thresholds = useMemo(() => {
    const nonzero = data
      .map((d) => d.layoff_total)
      .filter((v) => v > 0)
      .sort((a, b) => a - b);
    if (nonzero.length === 0) return [];
    return [0.25, 0.5, 0.75].map(
      (q) => nonzero[Math.min(nonzero.length - 1, Math.floor(q * nonzero.length))],
    );
  }, [data]);

  const byCode = new Map(data.map((d) => [d.code, d]));
  const fills = Object.fromEntries(
    data.map((d) => [d.code, ramp.buckets[bucketOf(d.layoff_total, thresholds)]]),
  );

  const legend = thresholds.length
    ? [
        { color: ramp.buckets[0], label: "0" },
        { color: ramp.buckets[1], label: `1–${fmtCompact(thresholds[0])}` },
        {
          color: ramp.buckets[2],
          label: `${fmtCompact(thresholds[0])}–${fmtCompact(thresholds[1])}`,
        },
        {
          color: ramp.buckets[3],
          label: `${fmtCompact(thresholds[1])}–${fmtCompact(thresholds[2])}`,
        },
        { color: ramp.buckets[4], label: `> ${fmtCompact(thresholds[2])}` },
      ]
    : [{ color: ramp.buckets[0], label: "0" }];

  return (
    <UsMap
      fills={fills}
      srLabel="Map of layoffs by state. The state list below contains the same data as accessible links."
      tooltip={(code) => {
        const d = byCode.get(code);
        if (!d) return null;
        return (
          <>
            <div className="font-medium text-slate-900 dark:text-slate-100">{d.name}</div>
            <div className="text-slate-600 dark:text-slate-400">
              {fmtNum(d.notice_count)} {d.notice_count === 1 ? "notice" : "notices"}
            </div>
            <div className="text-slate-600 dark:text-slate-400">
              {fmtNum(d.layoff_total)} workers
            </div>
          </>
        );
      }}
      legend={
        <>
          <span className="font-medium text-slate-700 dark:text-slate-300">
            Workers affected
          </span>
          {legend.map((item, i) => (
            <span key={i} className="flex items-center gap-1.5">
              <span
                className="inline-block h-3 w-3 rounded-sm"
                style={{ backgroundColor: item.color }}
              />
              {item.label}
            </span>
          ))}
        </>
      }
    />
  );
}
