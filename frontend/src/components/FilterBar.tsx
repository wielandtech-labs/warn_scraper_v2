import { useEffect, useRef, useState } from "react";

import type { IndustryStat } from "../api/types";
import { daysAgoIso, fmtDate, stateName, US_STATES } from "../lib/format";

export interface FilterValues {
  state?: string;
  employer?: string;
  closure_category?: string;
  industry?: string;
  subsector?: string;
  min_layoffs?: number;
  after?: string;
  before?: string;
}

const FILTER_KEYS = [
  "state",
  "employer",
  "closure_category",
  "industry",
  "subsector",
  "min_layoffs",
  "after",
  "before",
] as const;

/** Every filter key explicitly `undefined` — spread over existing search
 *  params to clear them (a bare `{}` would leave them untouched). */
export const EMPTY_FILTERS: FilterValues = Object.fromEntries(
  FILTER_KEYS.map((k) => [k, undefined]),
) as FilterValues;

const CLOSURE_TYPES = ["Closure", "Layoff", "Non-WARN"] as const;

/* Shared look of every toolbar control: one 32px row. */
const FIELD =
  "h-8 rounded-md border border-slate-300 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900";

export interface FilterBarProps {
  values: FilterValues;
  /** `opts.replace` asks the page to replace (not push) the history entry —
   *  used for debounced typing so Back doesn't walk through keystrokes. */
  onChange: (next: FilterValues, opts?: { replace?: boolean }) => void;
  showEmployer?: boolean;
  /** Hide the After/Before inputs and quick presets — for pages where the
   *  date dimension isn't the notice date (e.g. the radar's horizon). */
  showDates?: boolean;
  /** When provided, render an Industry (NAICS sector) dropdown of these options. */
  industries?: IndustryStat[];
  /** Window (in days) the page applies when no dates are set — that preset
   *  shows as active, and "All" writes `after=ALL_TIME` so it stays
   *  distinguishable from the default. Resolve with `resolveAfter()`. */
  defaultDays?: number;
}

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

const PRESETS = [
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1yr", days: 365 },
  { label: "5yr", days: 365 * 5 },
  { label: "All", days: null },
] as const;

export function FilterBar({
  values,
  onChange,
  showEmployer = true,
  showDates = true,
  industries,
  defaultDays,
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
  const clearAll = () => {
    // Also drop uncommitted employer text — if it hasn't hit the URL yet the
    // sync effect won't fire, and the pending debounce would re-apply it.
    setEmployerInput("");
    onChange(EMPTY_FILTERS);
  };

  // Subsectors of the currently-selected sector (drives the drill-down dropdown).
  // Empty when no sector is selected (no match), so the dropdown stays hidden.
  const selectedSubsectors =
    industries?.find((i) => i.sector === values.industry)?.subsectors ?? [];

  return (
    // One toolbar row from lg up; below that it wraps, search first on its
    // own line. Labels live in aria-labels and each control's empty option.
    <div className="card mb-4 flex flex-wrap items-center gap-2 !p-2.5">
      {showEmployer && (
        <div className="relative min-w-[10rem] flex-1 basis-full sm:basis-48">
          <svg
            aria-hidden
            viewBox="0 0 20 20"
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 fill-slate-400"
          >
            <path d="M8.5 3a5.5 5.5 0 0 1 4.38 8.82l3.65 3.65a.75.75 0 1 1-1.06 1.06l-3.65-3.65A5.5 5.5 0 1 1 8.5 3Zm0 1.5a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" />
          </svg>
          <input
            type="search"
            aria-label="Employer search"
            className={`${FIELD} w-full pl-8`}
            placeholder="Search employers…"
            value={employerInput}
            onChange={(e) => setEmployerInput(e.target.value)}
          />
        </div>
      )}

      <select
        aria-label="State"
        className={FIELD}
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

      <select
        aria-label="Closure type"
        className={FIELD}
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

      {industries && (
        <select
          aria-label="Industry"
          className={`${FIELD} max-w-[10rem] xl:max-w-[14rem]`}
          value={values.industry || ""}
          // Changing the sector clears any subsector selection.
          onChange={(e) => update({ industry: e.target.value || undefined, subsector: undefined })}
        >
          <option value="">All industries</option>
          {industries.map((i) => (
            <option key={i.sector} value={i.sector}>
              {i.name} ({i.notice_count})
            </option>
          ))}
        </select>
      )}

      {industries && selectedSubsectors.length > 0 && (
        <select
          aria-label="Subsector"
          className={`${FIELD} max-w-[10rem] xl:max-w-[14rem]`}
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
      )}

      <input
        type="number"
        min={1}
        aria-label="Minimum workers affected"
        placeholder="Min. workers"
        title="Only notices reporting at least this many affected workers; notices with no reported count are excluded"
        className={`${FIELD} w-32`}
        value={values.min_layoffs ?? ""}
        onChange={(e) =>
          update({ min_layoffs: e.target.value ? Number(e.target.value) : undefined })
        }
      />

      {showDates && <DateMenu values={values} update={update} defaultDays={defaultDays} />}

      {hasAnyFilter && (
        <button
          type="button"
          onClick={clearAll}
          className="h-8 rounded-md px-2 text-sm font-medium text-sky-700 hover:bg-slate-100 dark:text-sky-400 dark:hover:bg-slate-800"
        >
          Clear
        </button>
      )}
    </div>
  );
}

/** The quick preset in force, if any (same rules the chips always used). */
function activePreset(
  values: Pick<FilterValues, "after" | "before">,
  defaultDays: number | undefined,
): (typeof PRESETS)[number] | undefined {
  const noDates = !values.after && !values.before;
  return PRESETS.find(({ days }) =>
    days === null
      ? defaultDays === undefined
        ? noDates
        : values.after === ALL_TIME && !values.before
      : (values.after === daysAgoIso(days) && !values.before) ||
        (days === defaultDays && noDates),
  );
}

/* The date range as one toolbar button: its label is the range in force, and
   it opens the quick presets plus the After/Before inputs. Closes on an
   outside click or Escape. */
function DateMenu({
  values,
  update,
  defaultDays,
}: {
  values: FilterValues;
  update: (patch: Partial<FilterValues>) => void;
  defaultDays?: number;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const preset = activePreset(values, defaultDays);
  const after = values.after === ALL_TIME ? undefined : values.after;
  const label = preset
    ? preset.days === null
      ? "All time"
      : `Last ${preset.label}`
    : after && values.before
      ? `${fmtDate(after)} – ${fmtDate(values.before)}`
      : after
        ? `Since ${fmtDate(after)}`
        : values.before
          ? `Until ${fmtDate(values.before)}`
          : "Any date";

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Date range: ${label}`}
        onClick={() => setOpen((v) => !v)}
        className={`${FIELD} inline-flex items-center gap-1.5 whitespace-nowrap`}
      >
        <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4 fill-slate-400">
          <path d="M6 2.75a.75.75 0 0 1 1.5 0V4h5V2.75a.75.75 0 0 1 1.5 0V4h.75A2.25 2.25 0 0 1 17 6.25v8.5A2.25 2.25 0 0 1 14.75 17h-9.5A2.25 2.25 0 0 1 3 14.75v-8.5A2.25 2.25 0 0 1 5.25 4H6V2.75ZM4.5 8.5v6.25c0 .41.34.75.75.75h9.5c.41 0 .75-.34.75-.75V8.5h-11Z" />
        </svg>
        {label}
        <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4 fill-slate-400">
          <path d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.17l3.71-3.94a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .02-1.06Z" />
        </svg>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Date range"
          className="absolute right-0 top-full z-30 mt-1.5 w-72 space-y-3 rounded-xl border border-slate-200 bg-white p-3 shadow-xl dark:border-slate-700 dark:bg-slate-900"
        >
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                aria-pressed={p === preset}
                onClick={() => {
                  if (p.days === null)
                    update({
                      after: defaultDays === undefined ? undefined : ALL_TIME,
                      before: undefined,
                    });
                  else update({ after: daysAgoIso(p.days), before: undefined });
                  setOpen(false);
                }}
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                  p === preset
                    ? "border border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                    : "border border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800/50"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                After
              </span>
              <input
                type="date"
                className={FIELD}
                value={after ?? ""}
                onChange={(e) => update({ after: e.target.value || undefined })}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Before
              </span>
              <input
                type="date"
                className={FIELD}
                value={values.before || ""}
                onChange={(e) => update({ before: e.target.value || undefined })}
              />
            </label>
          </div>
        </div>
      )}
    </div>
  );
}
