import type { TimeRange } from "../lib/timeRange";

// Range types and toRangeQuery live in lib/timeRange so this file only
// exports components (fast refresh).
export type { Bucket, TimeRange } from "../lib/timeRange";

const LABELS: Record<TimeRange, string> = {
  "30d": "30 days",
  "1y": "1 year",
  "5y": "5 years",
  all: "All time",
};

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
