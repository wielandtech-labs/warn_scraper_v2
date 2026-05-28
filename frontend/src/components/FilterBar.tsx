import { daysAgoIso, US_STATES } from "../lib/format";

export interface FilterValues {
  state?: string;
  employer?: string;
  after?: string;
  before?: string;
}

export interface FilterBarProps {
  values: FilterValues;
  onChange: (next: FilterValues) => void;
  showEmployer?: boolean;
}

const PRESETS = [
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1yr", days: 365 },
  { label: "All", days: null },
] as const;

export function FilterBar({ values, onChange, showEmployer = true }: FilterBarProps) {
  const update = (patch: Partial<FilterValues>) => {
    const next: FilterValues = { ...values, ...patch };
    // Strip empty strings so they don't end up in the URL.
    (Object.keys(next) as (keyof FilterValues)[]).forEach((k) => {
      if (next[k] === "") delete next[k];
    });
    onChange(next);
  };

  return (
    <div className="card mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
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
          {US_STATES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>

      {showEmployer && (
        <label className="flex flex-col gap-1 lg:col-span-2">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Employer search
          </span>
          <input
            type="search"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            placeholder="e.g. Acme"
            value={values.employer || ""}
            onChange={(e) => update({ employer: e.target.value || undefined })}
          />
        </label>
      )}

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
      </div>
    </div>
  );
}
