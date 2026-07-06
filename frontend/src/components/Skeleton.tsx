/**
 * Pulsing gray placeholders shown while queries load. Each variant is sized to
 * match the content it stands in for, so the page doesn't shift when data
 * arrives. All are aria-hidden — screen readers get the loaded content only.
 */

export function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded bg-slate-200 dark:bg-slate-700 ${className}`} />;
}

/** Stand-in for a chart body. Height must match the chart it replaces. */
export function SkeletonChart({ height = 300 }: { height?: number }) {
  return (
    <div aria-hidden className="animate-pulse rounded bg-slate-100 dark:bg-slate-800" style={{ height }} />
  );
}

/** Stand-in for a divided list of link rows (recent notices, top employers). */
export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div aria-hidden className="divide-y divide-slate-100 dark:divide-slate-800">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="animate-pulse space-y-2 px-4 py-3">
          <div className="h-4 rounded bg-slate-200 dark:bg-slate-700" style={{ width: `${40 + ((i * 13) % 35)}%` }} />
          <div className="h-3 w-1/4 rounded bg-slate-200 dark:bg-slate-700" />
        </div>
      ))}
    </div>
  );
}

/** Stand-in for a DataTable: header band plus striped rows. */
export function SkeletonTable({ rows = 10 }: { rows?: number }) {
  return (
    <div aria-hidden className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="h-9 border-b border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950" />
      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="px-3 py-3">
            <div
              className="h-4 animate-pulse rounded bg-slate-200 dark:bg-slate-700"
              style={{ width: `${55 + ((i * 17) % 40)}%` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
