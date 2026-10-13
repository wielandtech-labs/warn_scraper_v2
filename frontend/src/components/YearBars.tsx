import { fmtNum } from "../lib/format";

/* Workers affected per year as plain CSS columns -- a dozen bars don't need
   Recharts (~100 KB gz) on a page that otherwise has no chart. Missing years
   between the first and last filing render as empty slots, so gaps read as
   gaps. Each column carries its numbers in an accessible title. */
export function YearBars({
  rows,
  height = 140,
}: {
  rows: { year: number; notice_count: number; layoff_total: number }[];
  height?: number;
}) {
  if (rows.length === 0) return null;
  const byYear = new Map(rows.map((r) => [r.year, r]));
  const first = rows[0].year;
  const last = rows[rows.length - 1].year;
  const years = Array.from({ length: last - first + 1 }, (_, i) => first + i);
  const max = Math.max(1, ...rows.map((r) => r.layoff_total));
  // Label every year when they fit, else every few (plus the last year when
  // it doesn't crowd its neighbour).
  const step = years.length <= 12 ? 1 : Math.ceil(years.length / 8);
  return (
    <div>
      <div className="flex items-end gap-1" style={{ height }}>
        {years.map((y) => {
          const r = byYear.get(y);
          const pct = r ? Math.max(r.layoff_total > 0 ? 2 : 0, (r.layoff_total / max) * 100) : 0;
          const label = r
            ? `${y}: ${fmtNum(r.layoff_total)} workers, ${fmtNum(r.notice_count)} ${r.notice_count === 1 ? "notice" : "notices"}`
            : `${y}: no notices`;
          return (
            <div key={y} className="group relative flex h-full flex-1 items-end" title={label}>
              <div
                className="w-full rounded-t-sm bg-brand/75 transition-colors group-hover:bg-brand"
                style={{ height: `${pct}%` }}
              />
              <span className="sr-only">{label}</span>
            </div>
          );
        })}
      </div>
      <div aria-hidden className="mt-1.5 flex gap-1 border-t border-slate-200 pt-1 dark:border-slate-800">
        {years.map((y, i) => (
          <div key={y} className="flex-1 text-center text-[0.65rem] tabular-nums text-slate-500 dark:text-slate-400">
            {i % step === 0 || (i === years.length - 1 && i % step >= step / 2)
              ? `’${String(y).slice(2)}`
              : ""}
          </div>
        ))}
      </div>
    </div>
  );
}
