import type { ReactNode } from "react";

/* The editorial page opening shared by the top-level pages: a brand-red
   kicker, the serif title, an optional one-paragraph lede, and actions or a
   small figure on the right. Keeps every page's first screen consistent with
   the dashboard hero without each page re-deriving the type scale. */
export function PageHeader({
  kicker,
  title,
  lede,
  aside,
}: {
  kicker: ReactNode;
  title: ReactNode;
  lede?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 border-b border-slate-200 pb-5 sm:flex-row sm:items-end sm:justify-between dark:border-slate-800">
      <div className="min-w-0">
        <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-brand">{kicker}</p>
        <h1 className="mt-1.5 text-3xl font-semibold leading-tight text-slate-900 dark:text-slate-50">
          {title}
        </h1>
        {lede && (
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-600 dark:text-slate-400">
            {lede}
          </p>
        )}
      </div>
      {aside && <div className="shrink-0">{aside}</div>}
    </header>
  );
}
