import { useEffect } from "react";

/**
 * Set document.title for the lifetime of a route component, restoring the
 * previous title on unmount. The server injects per-route <title> for crawlers
 * (see warn_v2/api/seo.py); this keeps the tab title correct during in-app
 * client-side navigation, where no full page load happens.
 */
export function useDocumentTitle(title: string | undefined): void {
  useEffect(() => {
    if (!title) return;
    const prev = document.title;
    document.title = title;
    return () => {
      document.title = prev;
    };
  }, [title]);
}
