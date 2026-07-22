/** Footnote under a time-series chart explaining the dashed 6-month forecast. */
export function ForecastNote({ lastHistoryLabel }: { lastHistoryLabel: string }) {
  return (
    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
      Dashed extension: statistical 6-month forecast fitted to monthly history
      through {lastHistoryLabel}; shaded band is the 80% prediction interval.
      Updated weekly — a model projection, not recorded data.
    </p>
  );
}
