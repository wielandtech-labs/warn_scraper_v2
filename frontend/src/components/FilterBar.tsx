import { useEffect, useState } from "react";

import type { IndustryStat } from "../api/types";
import { daysAgoIso, stateName, US_STATES } from "../lib/format";

export interface FilterValues {
  state?: string;
  employer?: string;
  closure_category?: string;
  industry?: string;
  subsector?: string;
  after?: string;
  before?: string;
}

const FILTER_KEYS = [
  "state",
  "employer",
  "closure_category",
  "industry",
  "subsector",
  "after",
  "before",
] as const;

/** Every filter key explicitly `undefined` — spread over existing search
 *  params to clear them (a bare `{}` would leave them untouched). */
export const EMPTY_FILTERS: FilterValues = Object.fromEntries(
  FILTER_KEYS.map((k) => [k, undefined]),
) as FilterValues;

const CLOSURE_TYPES = ["Closure", "Layoff"] as const;

export interface FilterBarProps {
  values: FilterValues;
  /** `opts.replace` asks the page to replace (not push) the history entry —
   *  used for debounced typing so Back doesn't walk through keystrokes. */
  onChange: (next: FilterValues, opts?: { replace?: boolean }) => void;
  showEmployer?: boolean;
  /** When provided, render an Industry (NAICS sector) dropdown of these options. */
  industries?: IndustryStat[];
}

const PRESETS = [
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1yr", days: 365 },
  { label: "All", days: null },
] as const;

export function FilterBar({
  values,
  onChange,
  showEmployer = true,
  industries,
}: FilterBarProps) {
  const update = (patch: Partial<FilterValues>, opts?: { replace?: boolean }) => {
    const next: FilterValues = { ...values, ...patch };
    // Strip empty strings so they don't end up in the URL.
    (Object.keys(next) as (keyof FilterValues)[]).forEach((k) => {
      if (next[k] === "") delete next[k];
    });
    onChange(next, opts);
  };

  // Employer input is kept locally and applied after a debounce, so each
  // keystroke doesn't fire an API query and push a history entry.
  const [employerInput, setEmployerInput] = useState(values.employer ?? "");
  useEffect(() => {
    // External change (back/forward, Clear all) wins over stale local input.
    setEmployerInput(values.employer ?? "");
  }, [values.employer]);
  // `values` is a dep so a pending timer is rescheduled with the current
  // filters — otherwise firing it would merge the employer into a stale
  // snapshot and drop a dropdown change made during the debounce window.
  useEffect(() => {
    if ((values.employer ?? "") === employerInput) return;
    const t = setTimeout(
      () => update({ employer: employerInput || undefined }, { replace: true }),
      300,
    );
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employerInput, values]);

  const hasAnyFilter = FILTER_KEYS.some((k) => values[k]);
  const clearAll = () => onChange(EMPTY_FILTERS);

  // Subsectors of the currently-selected sector (drives the drill-down dropdown).
  // Empty when no sector is selected (no match), so the dropdown stays hidden.
  const selectedSubsectors =
    industries?.find((i) => i.sector === values.industry)?.subsectors ?? [];

  return (
    <div className="card mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-7">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
          State
        </span>
        <select
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          value={values.state || ""}
          onChange={(e) => update({ state: e.target.value || undefined })}
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

      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
          Closure type
        </span>
        <select
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          value={values.closure_category || ""}
          onChange={(e) => update({ closure_category: e.target.value || undefined })}
        >
          <option value="">All types</option>
          {CLOSURE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      {industries && (
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Industry
          </span>
          <select
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={values.industry || ""}
            // Changing the sector clears any subsector selection.
            onChange={(e) =>
              update({ industry: e.target.value || undefined, subsector: undefined })
            }
          >
            <option value="">All industries</option>
            {industries.map((i) => (
              <option key={i.sector} value={i.sector}>
                {i.name} ({i.notice_count})
              </option>
            ))}
          </select>
        </label>
      )}

      {industries && selectedSubsectors.length > 0 && (
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Subsector
          </span>
          <select
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={values.subsector || ""}
            onChange={(e) => update({ subsector: e.target.value || undefined })}
          >
            <option value="">All subsectors</option>
            {selectedSubsectors.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name} ({s.notice_count})
              </option>
            ))}
          </select>
        </label>
      )}

      {showEmployer && (
        <label className="flex flex-col gap-1 lg:col-span-2">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Employer search
          </span>
          <input
            type="search"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            placeholder="e.g. Acme"
            value={employerInput}
            onChange={(e) => setEmployerInput(e.target.value)}
          />
        </label>
      )}

      {/* After + Before share one grid cell so the date range never splits
          across rows (it wraps as a pair when the row overflows). */}
      <div className="grid grid-cols-2 gap-3 sm:col-span-2 lg:col-span-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            After
          </span>
          <input
            type="date"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={values.after || ""}
            onChange={(e) => update({ after: e.target.value || undefined })}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Before
          </span>
          <input
            type="date"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={values.before || ""}
            onChange={(e) => update({ before: e.target.value || undefined })}
          />
        </label>
      </div>

      {/* Quick date presets */}
      <div className="col-span-full flex items-center gap-1.5">
        <span className="text-xs text-slate-400">Quick:</span>
        {PRESETS.map(({ label, days }) => {
          const active =
            days === null
              ? !values.after && !values.before
              : values.after === daysAgoIso(days) && !values.before;
          return (
            <button
              key={label}
              type="button"
              aria-pressed={active}
              onClick={() =>
                days === null
                  ? update({ after: undefined, before: undefined })
                  : update({ after: daysAgoIso(days), before: undefined })
              }
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                active
                  ? "bg-sky-700 text-white"
                  : "border border-slate-300 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {label}
            </button>
          );
        })}
        {hasAnyFilter && (
          <button
            type="button"
            onClick={clearAll}
            className="ml-auto text-xs font-medium text-sky-700 hover:underline"
          >
            Clear all filters
          </button>
        )}
      </div>
    </div>
  );
}
