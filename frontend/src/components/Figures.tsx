import type { ReactNode } from "react";

/* The hairline-ruled strip of headline numbers that opens a data page
   (stats, a state, a company, a notice). `value === null` renders a
   placeholder bar, so callers can lay the strip out before data arrives. */
export function Figures({ children, cols = 4 }: { children: ReactNode; cols?: 3 | 4 }) {
  return (
    <dl
      className={`grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 dark:border-slate-800 dark:bg-slate-800 ${cols === 3 ? "sm:grid-cols-3" : "sm:grid-cols-4"}`}
    >
      {children}
    </dl>
  );
}

export function Figure({
  label,
  value,
  note,
  accent = false,
}: {
  label: string;
  value: ReactNode | null;
  note?: ReactNode;
  accent?: boolean;
}) {
  return (
    <div className="bg-white p-4 dark:bg-slate-900">
      <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
        {label}
      </dt>
      <dd
        className={`mt-1 font-display text-2xl font-semibold tabular-nums ${accent ? "text-brand dark:text-brand-dark" : "text-slate-900 dark:text-slate-50"}`}
      >
        {value ?? <span className="inline-block h-7 w-20 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />}
      </dd>
      {note && <div className="text-xs text-slate-500 dark:text-slate-400">{note}</div>}
    </div>
  );
}
