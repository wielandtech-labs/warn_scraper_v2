import type { IndustryStat } from "../api/types";
import { fmtDate, fmtNum, stateName } from "../lib/format";
import { ALL_TIME, EMPTY_FILTERS, type FilterValues } from "./FilterBar";

/* The filters in force, as removable chips -- so a reader scanning a result
   list can see (and undo) what it is narrowed to without re-reading the
   whole FilterBar. Renders nothing when no filter is set. */
export function ActiveFilters({
  values,
  industries,
  onChange,
}: {
  values: FilterValues;
  industries?: IndustryStat[];
  onChange: (next: FilterValues) => void;
}) {
  const sector = industries?.find((i) => i.sector === values.industry);
  const chips: { key: string; label: string; clear: Partial<FilterValues> }[] = [];
  if (values.state) chips.push({ key: "state", label: stateName(values.state), clear: { state: undefined } });
  if (values.employer)
    chips.push({ key: "employer", label: `“${values.employer}”`, clear: { employer: undefined } });
  if (values.closure_category)
    chips.push({ key: "closure", label: values.closure_category, clear: { closure_category: undefined } });
  if (values.industry)
    chips.push({
      key: "industry",
      label: sector?.name ?? `NAICS ${values.industry}`,
      clear: { industry: undefined, subsector: undefined },
    });
  if (values.subsector) {
    const sub = sector?.subsectors.find((s) => s.code === values.subsector);
    chips.push({ key: "subsector", label: sub?.name ?? values.subsector, clear: { subsector: undefined } });
  }
  if (values.min_layoffs)
    chips.push({ key: "min", label: `≥ ${fmtNum(values.min_layoffs)} workers`, clear: { min_layoffs: undefined } });
  if (values.after && values.after !== ALL_TIME)
    chips.push({ key: "after", label: `From ${fmtDate(values.after)}`, clear: { after: undefined } });
  if (values.before) chips.push({ key: "before", label: `To ${fmtDate(values.before)}`, clear: { before: undefined } });
  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      {chips.map((c) => (
        <span
          key={c.key}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white py-0.5 pl-3 pr-1 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
        >
          {c.label}
          <button
            type="button"
            onClick={() => onChange({ ...values, ...c.clear })}
            aria-label={`Remove filter ${c.label}`}
            className="rounded-full px-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          >
            ×
          </button>
        </span>
      ))}
      {chips.length > 1 && (
        <button
          type="button"
          onClick={() => onChange(EMPTY_FILTERS)}
          className="text-xs font-medium text-slate-500 hover:text-slate-900 hover:underline dark:text-slate-400 dark:hover:text-slate-100"
        >
          Clear all
        </button>
      )}
    </div>
  );
}
