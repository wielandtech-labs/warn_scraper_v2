import { daysAgoIso } from "../lib/format";

// Two windows backing the dashboard / state-page views. "30d" pairs with daily
// time-series buckets, "1y" with monthly — see toRangeQuery().
export type TimeRange = "30d" | "1y";

const RANGE_DAYS: Record<TimeRange, number> = { "30d": 30, "1y": 365 };
const RANGE_BUCKET: Record<TimeRange, "day" | "month"> = { "30d": "day", "1y": "month" };

const LABELS: Record<TimeRange, string> = { "30d": "30 days", "1y": "1 year" };

/** Resolve a range into the API params it implies: an `after` cutoff (no
 *  `before` — windows run up to today) and the matching time-series bucket. */
export function toRangeQuery(range: TimeRange): { after: string; bucket: "day" | "month" } {
  return { after: daysAgoIso(RANGE_DAYS[range]), bucket: RANGE_BUCKET[range] };
}

export function TimeRangeToggle({
  value,
  onChange,
}: {
  value: TimeRange;
  onChange: (next: TimeRange) => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-slate-300 bg-white p-0.5 shadow-sm">
      {(Object.keys(LABELS) as TimeRange[]).map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={value === r}
          onClick={() => onChange(r)}
          className={
            "rounded px-3 py-1 text-sm font-medium transition-colors " +
            (value === r
              ? "bg-sky-700 text-white"
              : "text-slate-700 hover:bg-slate-100")
          }
        >
          {LABELS[r]}
        </button>
      ))}
    </div>
  );
}
