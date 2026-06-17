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
}: {
  title: string;
  docTitle: string;
  intro?: string;
  children: ReactNode;
}) {
  useDocumentTitle(docTitle);
  return (
    <article className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {intro && <p className="mt-2 text-slate-600">{intro}</p>}
      <div className="mt-4 space-y-4 text-slate-700 [&_a]:text-sky-700 [&_a]:underline [&_h2]:mt-6 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-slate-900 [&_li]:mt-1 [&_ul]:list-disc [&_ul]:pl-6">
        {children}
      </div>
    </article>
  );
}
