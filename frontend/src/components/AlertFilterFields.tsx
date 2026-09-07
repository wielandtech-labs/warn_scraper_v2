import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { AlertFilters } from "../api/types";
import { stateName, US_STATES } from "../lib/format";

const CLOSURE_TYPES = ["Closure", "Layoff", "Non-WARN"] as const;

const INPUT =
  "rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const LABEL =
  "text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400";

/**
 * The criteria inputs for one email alert, shared by the signup form and the
 * management page so both offer exactly the filters the digest can match on.
 *
 * `values` is the complete filter set (the API replaces it wholesale on save),
 * and `onChange` receives the whole set back with one field patched.
 */
export function AlertFilterFields({
  values,
  onChange,
  showState = true,
}: {
  values: AlertFilters;
  onChange: (next: AlertFilters) => void;
  /** Hide the state select where the page already fixes the state. */
  showState?: boolean;
}) {
  // Same source as the notices FilterBar, so the sector list and its counts
  // never drift between filtering notices and subscribing to them.
  const industries = useQuery({
    queryKey: ["stats", "industries"],
    queryFn: () => api.statsIndustries(),
  });
  const sectors = industries.data ?? [];
  const subsectors = sectors.find((i) => i.sector === values.industry)?.subsectors ?? [];

  const update = (patch: AlertFilters) => onChange({ ...values, ...patch });

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {showState && (
        <label className="flex flex-col gap-1">
          <span className={LABEL}>State</span>
          <select
            className={INPUT}
            value={values.state || ""}
            onChange={(e) => update({ state: e.target.value || null })}
          >
            <option value="">All states</option>
            {[...US_STATES]
              .sort((a, b) => stateName(a).localeCompare(stateName(b)))
              .map((s) => (
                <option key={s} value={s}>
                  {stateName(s)}
                </option>
              ))}
          </select>
        </label>
      )}

      <label className="flex flex-col gap-1">
        <span className={LABEL}>Industry</span>
        <select
          className={INPUT}
          value={values.industry || ""}
          // Changing the sector clears any subsector selection.
          onChange={(e) => update({ industry: e.target.value || null, subsector: null })}
        >
          <option value="">All industries</option>
          {sectors.map((i) => (
            <option key={i.sector} value={i.sector}>
              {i.name}
            </option>
          ))}
        </select>
      </label>

      {subsectors.length > 0 && (
        <label className="flex flex-col gap-1">
          <span className={LABEL}>Subsector</span>
          <select
            className={INPUT}
            value={values.subsector || ""}
            onChange={(e) => update({ subsector: e.target.value || null })}
          >
            <option value="">All subsectors</option>
            {subsectors.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="flex flex-col gap-1">
        <span className={LABEL}>Closure type</span>
        <select
          className={INPUT}
          value={values.closure_category || ""}
          onChange={(e) => update({ closure_category: e.target.value || null })}
        >
          <option value="">All types</option>
          {CLOSURE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className={LABEL}>Minimum affected</span>
        <input
          type="number"
          min={1}
          max={100000}
          className={INPUT}
          placeholder="Any size"
          value={values.min_layoffs ?? ""}
          onChange={(e) =>
            update({ min_layoffs: e.target.value ? Number(e.target.value) : null })
          }
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className={LABEL}>Employer contains</span>
        <input
          type="search"
          maxLength={256}
          className={INPUT}
          placeholder="e.g. Acme"
          value={values.employer_query ?? ""}
          onChange={(e) => update({ employer_query: e.target.value || null })}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className={LABEL}>Frequency</span>
        <select
          className={INPUT}
          value={values.frequency || "daily"}
          onChange={(e) => update({ frequency: e.target.value as "daily" | "weekly" })}
        >
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
        </select>
      </label>

      <p className="text-xs text-slate-400 sm:col-span-2 dark:text-slate-500">
        A minimum size only matches notices that report a headcount — many
        don&apos;t. An industry filter only matches notices we&apos;ve linked to a
        company with a NAICS code.
      </p>
    </div>
  );
}
