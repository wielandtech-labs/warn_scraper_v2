import type { CSSProperties } from "react";

import { fmtNum } from "../lib/format";

interface TooltipEntry {
  dataKey?: string | number;
  name?: string;
  value?: number | null;
  color?: string;
  payload?: Record<string, unknown>;
}

/** Custom tooltip for the time-series charts. The dashed projection series is
 *  seeded at the anchor point (last complete period) purely so the segment has
 *  somewhere to start; the default tooltip content would list those seeds as
 *  duplicate "(projected)" rows there. This drops them (only the projected
 *  point carries actual_* fields — see withProjectionSeries) and renders
 *  "N projected (M to date)" on the projected point. The forecast series
 *  (withForecastSeries) is seeded the same way at its anchor row
 *  (is_forecast_anchor), and its range Area contributes a raw [lo, hi] tuple
 *  entry that gets dropped here rather than mis-rendered as a number.
 *  contentStyle/labelStyle arrive from the host <Tooltip>, which clones this
 *  element with its props. */
export function ProjectionTooltip({
  active,
  payload,
  label,
  contentStyle,
  labelStyle,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
  contentStyle?: CSSProperties;
  labelStyle?: CSSProperties;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload ?? {};
  const entries = payload.filter((e) => {
    if (e.dataKey === "forecast_layoff_band") return false; // range area, not a text row
    if (e.value == null) return false; // the nulled solid series on the projected/forecast point
    if (e.dataKey === "projected_notice_count") {
      return typeof row.actual_notice_count === "number";
    }
    if (e.dataKey === "projected_layoff_total") {
      return typeof row.actual_layoff_total === "number";
    }
    if (e.dataKey === "forecast_notice_count" || e.dataKey === "forecast_layoff_total") {
      return row.is_forecast_anchor !== true;
    }
    return true;
  });
  if (entries.length === 0) return null;

  const fmtValue = (e: TooltipEntry): string => {
    if (e.dataKey === "projected_notice_count" && typeof row.actual_notice_count === "number") {
      return `${fmtNum(e.value)} projected (${fmtNum(row.actual_notice_count)} to date)`;
    }
    if (e.dataKey === "projected_layoff_total" && typeof row.actual_layoff_total === "number") {
      return `${fmtNum(e.value)} projected (${fmtNum(row.actual_layoff_total)} to date)`;
    }
    if (e.dataKey === "forecast_notice_count") {
      return typeof row.actual_notice_count === "number"
        ? `${fmtNum(e.value)} forecast (${fmtNum(row.actual_notice_count)} to date)`
        : `${fmtNum(e.value)} forecast`;
    }
    if (e.dataKey === "forecast_layoff_total") {
      const band = row.forecast_layoff_band as [number, number] | undefined;
      const range = Array.isArray(band) ? ` (${fmtNum(band[0])}–${fmtNum(band[1])})` : "";
      return typeof row.actual_layoff_total === "number"
        ? `${fmtNum(e.value)} forecast${range}, ${fmtNum(row.actual_layoff_total)} to date`
        : `${fmtNum(e.value)} forecast${range}`;
    }
    return fmtNum(e.value);
  };

  return (
    // Mirrors DefaultTooltipContent's inline styles so swapping in this custom
    // content is visually invisible aside from the dropped seed entries.
    <div
      style={{
        margin: 0,
        padding: 10,
        backgroundColor: "#fff",
        border: "1px solid #ccc",
        whiteSpace: "nowrap",
        ...contentStyle,
      }}
    >
      <p style={{ margin: 0, ...labelStyle }}>{label}</p>
      <ul style={{ padding: 0, margin: 0 }}>
        {entries.map((e) => (
          <li
            key={String(e.dataKey)}
            style={{ display: "block", paddingTop: 4, paddingBottom: 4, color: e.color }}
          >
            {e.name} : {fmtValue(e)}
          </li>
        ))}
      </ul>
    </div>
  );
}
