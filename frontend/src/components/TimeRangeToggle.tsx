import { daysAgoIso } from "../lib/format";

export type Bucket = "day" | "month" | "year";

// Windows backing the dashboard / state-page views, paired with the time-series
// bucket that keeps each chart readable: a month of days, a year of months, five
// years of months, all time by year. "all" has no `after` cutoff. See toRangeQuery().
export type TimeRange = "30d" | "1y" | "5y" | "all";

// Day counts for each bounded window; null = no cutoff (all time).
const RANGE_DAYS: Record<TimeRange, number | null> = {
  "30d": 30,
  "1y": 365,
  "5y": 365 * 5,
  all: null,
};
const RANGE_BUCKET: Record<TimeRange, Bucket> = {
  "30d": "day",
  "1y": "month",
  "5y": "month",
  all: "year",
};

const LABELS: Record<TimeRange, string> = {
  "30d": "30 days",
  "1y": "1 year",
  "5y": "5 years",
  all: "All time",
};

/** Resolve a range into the API params it implies: an `after` cutoff (omitted
 *  for all-time; no `before` — windows run up to today) and the matching
 *  time-series bucket. */
export function toRangeQuery(range: TimeRange): { after?: string; bucket: Bucket } {
  const days = RANGE_DAYS[range];
  return { after: days == null ? undefined : daysAgoIso(days), bucket: RANGE_BUCKET[range] };
}

export function TimeRangeToggle({
  value,
  onChange,
}: {
  value: TimeRange;
  onChange: (next: TimeRange) => void;
}) {
  return (
    <div className="inline-flex rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900">
      {(Object.keys(LABELS) as TimeRange[]).map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={value === r}
          onClick={() => onChange(r)}
          className={
            "rounded-full px-3 py-1 text-sm font-medium transition-colors " +
            (value === r
              ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
              : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100")
          }
        >
          {LABELS[r]}
        </button>
      ))}
    </div>
  );
}
