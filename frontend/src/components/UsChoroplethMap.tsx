import { useTheme } from "../hooks/useTheme";
import { fmtCompact, fmtNum } from "../lib/format";
import { CHOROPLETH } from "../lib/themeColors";
import { isUnpublished } from "../lib/unavailable";
import { UsMap } from "./UsMap";

interface StateDatum {
  code: string;
  name: string;
  notice_count: number;
  layoff_total: number;
}

export type ChoroplethMetric = "workers" | "notices";

function bucketOf(value: number, thresholds: number[]): number {
  if (value <= 0) return 0;
  for (let i = 0; i < thresholds.length; i++) {
    if (value <= thresholds[i]) return i + 1;
  }
  return thresholds.length + 1;
}

/** US choropleth shaded by layoff totals or notice counts. States that
 *  publish no figure for the metric are hatched and left out of the buckets,
 *  rather than shaded as a measured zero. */
export function UsChoroplethMap({
  data,
  metric,
  highlight,
  onHover,
}: {
  data: StateDatum[];
  metric: ChoroplethMetric;
  highlight?: string | null;
  onHover?: (code: string | null) => void;
}) {
  const { resolved } = useTheme();
  const ramp = CHOROPLETH[resolved][metric];

  const values = new Map(
    data
      .filter((d) => !isUnpublished(d.code, metric))
      .map((d) => [d.code, metric === "notices" ? d.notice_count : d.layoff_total]),
  );
  // Quartiles of the nonzero values: the distribution is heavily skewed
  // toward a few large states, so fixed linear buckets would leave most of
  // the country in the lowest one.
  const nonzero = [...values.values()].filter((v) => v > 0).sort((a, b) => a - b);
  const thresholds = nonzero.length
    ? [0.25, 0.5, 0.75].map(
        (q) => nonzero[Math.min(nonzero.length - 1, Math.floor(q * nonzero.length))],
      )
    : [];

  const byCode = new Map(data.map((d) => [d.code, d]));
  const hatched = data.filter((d) => !values.has(d.code)).map((d) => d.code);
  const fills = Object.fromEntries(
    data.map((d) => [d.code, ramp[bucketOf(values.get(d.code) ?? 0, thresholds)]]),
  );

  const legend = thresholds.length
    ? [
        { color: ramp[0], label: "0" },
        { color: ramp[1], label: `1–${fmtCompact(thresholds[0])}` },
        { color: ramp[2], label: `${fmtCompact(thresholds[0])}–${fmtCompact(thresholds[1])}` },
        { color: ramp[3], label: `${fmtCompact(thresholds[1])}–${fmtCompact(thresholds[2])}` },
        { color: ramp[4], label: `> ${fmtCompact(thresholds[2])}` },
      ]
    : [{ color: ramp[0], label: "0" }];

  return (
    <UsMap
      framed={false}
      fills={fills}
      hatched={hatched}
      highlight={highlight}
      onHover={onHover}
      srLabel="Map of layoffs by state. The state list on this page contains the same data as accessible links."
      tooltip={(code) => {
        const d = byCode.get(code);
        if (!d) return null;
        return (
          <>
            <div className="font-medium text-slate-900 dark:text-slate-100">{d.name}</div>
            <div className="text-slate-600 dark:text-slate-400">
              {isUnpublished(code, "notices")
                ? "No notices published"
                : `${fmtNum(d.notice_count)} ${d.notice_count === 1 ? "notice" : "notices"}`}
            </div>
            {!isUnpublished(code, "notices") && (
              <div className="text-slate-600 dark:text-slate-400">
                {isUnpublished(code, "workers")
                  ? "Worker counts not published"
                  : `${fmtNum(d.layoff_total)} workers`}
              </div>
            )}
          </>
        );
      }}
      legend={
        <>
          <span className="font-medium text-slate-700 dark:text-slate-300">
            {metric === "notices" ? "Notices" : "Workers affected"}
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
          {hatched.length > 0 && (
            <span className="flex items-center gap-1.5">
              <svg aria-hidden width={12} height={12} className="rounded-sm">
                <rect width={12} height={12} fill={ramp[0]} />
                <path
                  d="M-2 4 L4 -2 M-2 10 L10 -2 M4 14 L14 4"
                  className="stroke-slate-400 dark:stroke-slate-500"
                  strokeWidth={1.5}
                />
              </svg>
              Not published
            </span>
          )}
        </>
      }
    />
  );
}
