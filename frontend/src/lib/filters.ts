import type { FilterValues } from "../components/FilterBar";
import { daysAgoIso } from "./format";

// Kept out of FilterBar.tsx so that file only exports components (fast refresh).

/** `after` value meaning "no cutoff" on pages with a `defaultDays` window. */
export const ALL_TIME = "all";

/** The `after` to send to the API for a page with a `defaultDays` window:
 *  the default cutoff when no dates are set, none for ALL_TIME. */
export function resolveAfter(
  values: Pick<FilterValues, "after" | "before">,
  defaultDays: number,
): string | undefined {
  if (values.after === ALL_TIME) return undefined;
  if (!values.after && !values.before) return daysAgoIso(defaultDays);
  return values.after;
}
