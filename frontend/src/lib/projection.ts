// Reshapes time-series rows for the pace-projection dashed segment.
//
// The backend sets projected_notice_count / projected_layoff_total on the
// final row when it is the current, incomplete month/year. Recharts renders
// this via the null-padding pattern: the solid series are nulled at the final
// point (so they stop at the last complete period), and the dashed projection
// series are non-null only at the anchor (last complete point, seeded with its
// actual values) and the projected point. The two non-null dashed values are
// adjacent, so no connectNulls is needed.

import { fmtNum } from "./format";

interface SeriesRow {
  notice_count: number;
  layoff_total: number;
  projected_notice_count?: number | null;
  projected_layoff_total?: number | null;
}

export type ProjectedPoint<T> = Omit<T, "notice_count" | "layoff_total"> & {
  notice_count: number | null;
  layoff_total: number | null;
  projected_notice_count: number | null;
  projected_layoff_total: number | null;
  /** Actual to-date values, surfaced by the tooltip on the projected point. */
  actual_notice_count?: number;
  actual_layoff_total?: number;
};

export function withProjectionSeries<T extends SeriesRow>(
  rows: T[],
): { data: ProjectedPoint<T>[]; hasProjection: boolean } {
  const last = rows[rows.length - 1];
  // Need >= 2 rows so the dashed segment has an anchor to start from.
  const active = rows.length >= 2 && last.projected_notice_count != null;
  const data = rows.map((r, i): ProjectedPoint<T> => {
    if (active && i === rows.length - 1) {
      return {
        ...r,
        notice_count: null,
        layoff_total: null,
        projected_notice_count: r.projected_notice_count ?? null,
        projected_layoff_total: r.projected_layoff_total ?? null,
        actual_notice_count: r.notice_count,
        actual_layoff_total: r.layoff_total,
      } as ProjectedPoint<T>;
    }
    const anchor = active && i === rows.length - 2;
    return {
      ...r,
      projected_notice_count: anchor ? r.notice_count : null,
      projected_layoff_total: anchor ? r.layoff_total : null,
    } as ProjectedPoint<T>;
  });
  return { data, hasProjection: active };
}

/** Tooltip formatter shared by the time-series charts: plain numbers for the
 *  actual series, "N projected (M to date)" on the projected point. */
export function projectionTooltip(
  value: number,
  _name: string,
  item: { dataKey?: unknown; payload?: Record<string, unknown> },
): string {
  const p = item.payload ?? {};
  if (
    item.dataKey === "projected_notice_count" &&
    typeof p.actual_notice_count === "number"
  ) {
    return `${fmtNum(value)} projected (${fmtNum(p.actual_notice_count)} to date)`;
  }
  if (
    item.dataKey === "projected_layoff_total" &&
    typeof p.actual_layoff_total === "number"
  ) {
    return `${fmtNum(value)} projected (${fmtNum(p.actual_layoff_total)} to date)`;
  }
  return fmtNum(value);
}
