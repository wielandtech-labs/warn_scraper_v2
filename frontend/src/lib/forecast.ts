// Reshapes time-series rows for the dashed 6-month forecast extension.
//
// Mirrors withProjectionSeries' null-padding pattern (lib/projection.ts), but
// the dashed segment comes from a precomputed statistical forecast instead of
// a linear pace estimate, and it extends up to 6 points beyond the last
// history row rather than just completing the current period. When a
// forecast is active it supersedes the pace projection: callers should skip
// withProjectionSeries and render this instead.
import { fmtMonth } from "./format";
import type { Bucket } from "../components/TimeRangeToggle";
import type { ForecastOut } from "../api/types";

interface SeriesRow {
  period: string; // "YYYY-MM" for month buckets
  notice_count: number;
  layoff_total: number;
}

export type ForecastedPoint<T> = Omit<T, "notice_count" | "layoff_total"> & {
  notice_count: number | null;
  layoff_total: number | null;
  forecast_notice_count: number | null;
  forecast_layoff_total: number | null;
  /** [lo, hi] band for the layoffs series only — two overlapping bands read
   *  as noise, so the notices series gets a dashed line with no band. */
  forecast_layoff_band: [number, number] | null;
  /** Actual to-date values, surfaced by the tooltip on a row that carries
   *  both a solid actual and a forecast point (the current partial period). */
  actual_notice_count?: number;
  actual_layoff_total?: number;
  /** True only on the anchor row (last_history_month), where forecast_* is
   *  seeded to the same value as the solid series purely so the dashed line
   *  has somewhere to start — the tooltip uses this to skip the duplicate. */
  is_forecast_anchor?: boolean;
};

export function withForecastSeries<T extends SeriesRow & { label: string }>(
  rows: T[],
  forecast: ForecastOut | null | undefined,
  bucket: Bucket,
): { data: ForecastedPoint<T>[]; hasForecast: boolean } {
  const active =
    bucket === "month" &&
    !!forecast &&
    forecast.points.length > 0 &&
    rows.some((r) => r.period === forecast.last_history_month);

  if (!active || !forecast) {
    const data = rows.map(
      (r): ForecastedPoint<T> => ({
        ...r,
        forecast_notice_count: null,
        forecast_layoff_total: null,
        forecast_layoff_band: null,
      }),
    );
    return { data, hasForecast: false };
  }

  const firstForecastMonth = forecast.points[0].month;
  const byMonth = new Map(forecast.points.map((p) => [p.month, p]));

  const data: ForecastedPoint<T>[] = rows.map((r): ForecastedPoint<T> => {
    if (r.period === forecast.last_history_month) {
      // Anchor: seeded with its own actual values so the dashed line and
      // band start exactly where the solid line ends.
      return {
        ...r,
        forecast_notice_count: r.notice_count,
        forecast_layoff_total: r.layoff_total,
        forecast_layoff_band: [r.layoff_total, r.layoff_total],
        is_forecast_anchor: true,
      };
    }
    if (r.period >= firstForecastMonth) {
      // A history row already covering a forecast month — the current
      // partial period, if any notices have landed in it yet.
      const p = byMonth.get(r.period);
      return {
        ...r,
        notice_count: null,
        layoff_total: null,
        forecast_notice_count: p?.notice_count ?? null,
        forecast_layoff_total: p?.layoff_total ?? null,
        forecast_layoff_band: p ? [p.layoff_total_lo, p.layoff_total_hi] : null,
        actual_notice_count: r.notice_count,
        actual_layoff_total: r.layoff_total,
      };
    }
    return {
      ...r,
      forecast_notice_count: null,
      forecast_layoff_total: null,
      forecast_layoff_band: null,
    };
  });

  const covered = new Set(rows.map((r) => r.period));
  for (const p of forecast.points) {
    if (covered.has(p.month)) continue;
    data.push({
      ...({ period: p.month, label: fmtMonth(p.month) } as unknown as T),
      notice_count: null,
      layoff_total: null,
      forecast_notice_count: p.notice_count,
      forecast_layoff_total: p.layoff_total,
      forecast_layoff_band: [p.layoff_total_lo, p.layoff_total_hi],
    });
  }

  return { data, hasForecast: true };
}
