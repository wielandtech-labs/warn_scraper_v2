import { useState, type ReactNode } from "react";

/* Collapsed home for the absolute-level BLS cards (IndicatorChart) under a
   WARN chart. The comparison itself lives in WarnTimeChart's Compare mode;
   these stay one click away for readers who want the actual rates and counts.
   Children mount only once opened, so a closed section costs no requests. */
export function BlsLevels({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="group rounded-xl border border-slate-200 dark:border-slate-800"
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-sm font-medium text-slate-700 dark:text-slate-300">
        <span>Official BLS labour-market levels</span>
        <span aria-hidden className="text-slate-400 transition-transform group-open:rotate-90">
          ›
        </span>
      </summary>
      {open && <div className="space-y-6 border-t border-slate-200 p-4 dark:border-slate-800">{children}</div>}
    </details>
  );
}
