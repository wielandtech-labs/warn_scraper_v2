import type { MapPlacesTimeline, TimelineBucket } from "../api/client";
import type { StateStatusOut } from "../api/types";
import type { PlacesGeoJSON } from "../components/PlacesMap";

/* Pure helpers for /timelapse: period keys as the timeline endpoints write
   them ("2020", "2020-Q2", "2020-04"), and the per-frame views of their
   payloads. */

/** Roll a "YYYY-MM" month up to its bucket key (mirrors warn_v2/api/timeline.py). */
export function periodOf(month: string, bucket: TimelineBucket): string {
  if (bucket === "year") return month.slice(0, 4);
  if (bucket === "quarter") return `${month.slice(0, 4)}-Q${Math.floor((Number(month.slice(5, 7)) - 1) / 3) + 1}`;
  return month;
}

/** First month ("YYYY-MM") a period covers. */
export function periodStartMonth(period: string): string {
  if (period.length === 4) return `${period}-01`;
  const q = period.match(/^(\d{4})-Q(\d)$/);
  if (q) return `${q[1]}-${String((Number(q[2]) - 1) * 3 + 1).padStart(2, "0")}`;
  return period;
}

/** Last day of a period, as "YYYY-MM-DD" (for comparing ISO dates). */
export function periodEnd(period: string): string {
  const year = Number(period.slice(0, 4));
  const q = period.match(/-Q(\d)$/);
  const lastMonth = period.length === 4 ? 12 : q ? Number(q[1]) * 3 : Number(period.slice(5, 7));
  const lastDay = new Date(Date.UTC(year, lastMonth, 0)).getUTCDate();
  return `${year}-${String(lastMonth).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2020", "Q2 2020", "Apr 2020". */
export function periodLabel(period: string): string {
  const q = period.match(/^(\d{4})-Q(\d)$/);
  if (q) return `Q${q[2]} ${q[1]}`;
  if (period.length === 7) return `${MONTHS[Number(period.slice(5, 7)) - 1]} ${period.slice(0, 4)}`;
  return period;
}

/** The period today falls in. */
export function currentPeriod(bucket: TimelineBucket, today = new Date()): string {
  return periodOf(today.toISOString().slice(0, 7), bucket);
}

/** One GeoJSON collection per period of `periods`: each period's places with
 *  that period's counts. Built once per payload, so a frame change only hands
 *  the map a ready-made (small) collection. */
export function framesGeoJSON(t: MapPlacesTimeline, periods: string[]): PlacesGeoJSON[] {
  const frameOf = new Map(periods.map((p, i) => [p, i]));
  const out: PlacesGeoJSON[] = periods.map(() => ({ type: "FeatureCollection", features: [] }));
  for (let k = 0; k < t.place.length; k++) {
    const f = frameOf.get(t.periods[t.period[k]]);
    if (f === undefined) continue;
    const i = t.place[k];
    const lat = t.lat[i];
    const lon = t.lon[i];
    out[f].features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: { n: t.notices[k], w: t.workers[k], label: t.label[i], lat, lon },
    });
  }
  return out;
}

/** Workers at which the heatmap saturates: the 95th percentile of the
 *  per-(place, period) worker counts, so one scale serves every frame and the
 *  biggest periods saturate without washing out the rest. */
export function heatScaleMax(t: MapPlacesTimeline): number {
  if (t.workers.length === 0) return 1;
  const sorted = [...t.workers].sort((a, b) => a - b);
  return Math.max(1, sorted[Math.floor(0.95 * (sorted.length - 1))]);
}

/** States whose archive reaches back into `period` (its coverage starts on
 *  or before the period's last day), out of every state with a scraper. A
 *  state outside this set has no data yet — not zero layoffs. */
export function statesReporting(status: StateStatusOut[], period: string): Set<string> {
  const end = periodEnd(period);
  return new Set(
    status.filter((s) => s.coverage_start && s.coverage_start <= end).map((s) => s.state),
  );
}
