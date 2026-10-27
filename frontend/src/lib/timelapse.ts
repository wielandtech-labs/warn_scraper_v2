import type { IndustryTimeline, MapPlaces, MapPlacesTimeline, TimelineBucket } from "../api/client";
import type { StateStatusOut } from "../api/types";
import type { PlacesGeoJSON } from "../components/PlacesMap";

/* Pure helpers for /map's timeline: period keys as the timeline endpoints
   write them ("2020", "2020-Q2", "2020-04"), the roll-up from the monthly
   payloads the page loads to the bucket on screen, and the per-frame views
   of those payloads. */

export const DEFAULT_SINCE = 2015;
// Window starts offered. 1999 is the earliest any state's backfill reaches (IL).
export const WINDOWS = [
  [2015, "Since 2015"],
  [2010, "Since 2010"],
  [1999, "Since 1999"],
] as const;

/** The narrowest offered window that still reaches back to `year`. */
export function windowFor(year: number): number {
  return WINDOWS.find(([y]) => y <= year)?.[0] ?? WINDOWS[WINDOWS.length - 1][0];
}

/** Roll a "YYYY-MM" month up to its bucket key (mirrors warn_v2/api/timeline.py). */
export function periodOf(month: string, bucket: TimelineBucket): string {
  if (bucket === "year") return month.slice(0, 4);
  if (bucket === "quarter") return `${month.slice(0, 4)}-Q${Math.floor((Number(month.slice(5, 7)) - 1) / 3) + 1}`;
  return month;
}

function ordinal(period: string, bucket: TimelineBucket): number {
  const year = Number(period.slice(0, 4));
  if (bucket === "year") return year;
  if (bucket === "quarter") return year * 4 + Number(period[6]) - 1;
  return year * 12 + Number(period.slice(5, 7)) - 1;
}

function fromOrdinal(n: number, bucket: TimelineBucket): string {
  if (bucket === "year") return String(n);
  if (bucket === "quarter") return `${Math.floor(n / 4)}-Q${(n % 4) + 1}`;
  return `${Math.floor(n / 12)}-${String((n % 12) + 1).padStart(2, "0")}`;
}

/** Every period from the earliest to the latest of `periods`, in order
 *  (mirrors period_range in warn_v2/api/timeline.py). */
export function periodRange(periods: Iterable<string>, bucket: TimelineBucket): string[] {
  const ords = [...periods].map((p) => ordinal(p, bucket));
  if (ords.length === 0) return [];
  const lo = Math.min(...ords);
  const hi = Math.max(...ords);
  return Array.from({ length: hi - lo + 1 }, (_, i) => fromOrdinal(lo + i, bucket));
}

/** A monthly place timeline rolled up to `bucket`, shaped as the endpoint
 *  would return it for that bucket. The page loads months once per filter
 *  set, so a bucket switch costs no request. */
export function rollupPlaces(t: MapPlacesTimeline, bucket: TimelineBucket): MapPlacesTimeline {
  if (bucket === "month") return t;
  const cells = new Map<string, { place: number; period: string; n: number; w: number }>();
  for (let k = 0; k < t.place.length; k++) {
    const period = periodOf(t.periods[t.period[k]], bucket);
    const key = `${period}|${t.place[k]}`;
    const c = cells.get(key);
    if (c) {
      c.n += t.notices[k];
      c.w += t.workers[k];
    } else cells.set(key, { place: t.place[k], period, n: t.notices[k], w: t.workers[k] });
  }
  const periods = periodRange(new Set([...cells.values()].map((c) => c.period)), bucket);
  const index = new Map(periods.map((p, i) => [p, i]));
  const ordered = [...cells.values()].sort(
    (a, b) => index.get(a.period)! - index.get(b.period)! || a.place - b.place,
  );
  return {
    periods,
    lat: t.lat,
    lon: t.lon,
    label: t.label,
    place: ordered.map((c) => c.place),
    period: ordered.map((c) => index.get(c.period)!),
    notices: ordered.map((c) => c.n),
    workers: ordered.map((c) => c.w),
  };
}

/** A monthly industry timeline rolled up to `bucket`. */
export function rollupIndustries(t: IndustryTimeline, bucket: TimelineBucket): IndustryTimeline {
  if (bucket === "month") return t;
  const periods = periodRange(new Set(t.periods.map((m) => periodOf(m, bucket))), bucket);
  const index = new Map(periods.map((p, i) => [p, i]));
  const slot = t.periods.map((m) => index.get(periodOf(m, bucket))!);
  return {
    periods,
    sectors: t.sectors.map((s) => {
      const notices = new Array<number>(periods.length).fill(0);
      const workers = new Array<number>(periods.length).fill(0);
      s.notices.forEach((n, i) => (notices[slot[i]] += n));
      s.workers.forEach((w, i) => (workers[slot[i]] += w));
      return { ...s, notices, workers };
    }),
  };
}

/** The whole timeline as a single frame (every period summed), for the
 *  industry ranking while the map shows all dates. */
export function wholeWindow(t: IndustryTimeline): IndustryTimeline {
  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
  return {
    periods: ["all"],
    sectors: t.sectors.map((s) => ({ ...s, notices: [sum(s.notices)], workers: [sum(s.workers)] })),
  };
}

/** Per-place totals over every period, in /api/map-places' shape: what place
 *  search ranks and jumps to while a period is on the map. */
export function placesOfTimeline(t: MapPlacesTimeline): MapPlaces {
  const notices = new Array<number>(t.lat.length).fill(0);
  const workers = new Array<number>(t.lat.length).fill(0);
  for (let k = 0; k < t.place.length; k++) {
    notices[t.place[k]] += t.notices[k];
    workers[t.place[k]] += t.workers[k];
  }
  return { lat: t.lat, lon: t.lon, label: t.label, notices, workers };
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
