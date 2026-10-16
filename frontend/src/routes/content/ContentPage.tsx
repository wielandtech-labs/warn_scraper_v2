import type { ReactNode } from "react";

import { useDocumentTitle } from "../../hooks/useDocumentTitle";

/**
 * Shared shell for static content pages (About, WARN Act, FAQ, etc.).
 * Styles nested headings/links/lists via arbitrary variants so we don't depend
 * on the Tailwind typography plugin. The server injects per-route <title>/meta
 * for crawlers (warn_v2/api/seo.py); useDocumentTitle keeps the tab title in
 * sync during client-side navigation.
 */
export function ContentPage({
  title,
  docTitle,
  intro,
  children,
  maxWidth = "max-w-3xl",
}: {
  title: string;
  docTitle: string;
  intro?: string;
  children: ReactNode;
  maxWidth?: string;
}) {
  useDocumentTitle(docTitle);
  return (
    <article className={`mx-auto ${maxWidth}`}>
      <header className="border-b border-slate-200 pb-5 dark:border-slate-800">
        <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-brand">WARN Index</p>
        <h1 className="mt-1.5 text-3xl font-semibold leading-tight text-slate-900 dark:text-slate-50">
          {title}
        </h1>
        {intro && (
          <p className="mt-2 text-lg leading-relaxed text-slate-600 dark:text-slate-400">{intro}</p>
        )}
      </header>
      <div className="mt-6 space-y-4 leading-relaxed text-slate-700 [&_a]:text-sky-700 [&_a]:underline [&_h2]:mt-6 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-slate-900 [&_li]:mt-1 [&_ul]:list-disc [&_ul]:pl-6 dark:text-slate-300 dark:[&_a]:text-sky-400 dark:[&_h2]:text-slate-100">
        {children}
      </div>
    </article>
  );
}
