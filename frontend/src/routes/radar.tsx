import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import { api } from "../api/client";
import { ClosureBadge } from "../components/ClosureBadge";
import { CompanyLogo } from "../components/CompanyLogo";
import { DataTable } from "../components/DataTable";
import { EMPTY_FILTERS, FilterBar, type FilterValues } from "../components/FilterBar";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { QueryError } from "../components/QueryError";
import { SkeletonTable } from "../components/Skeleton";
import { StateSilhouette } from "../components/StateSilhouette";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum } from "../lib/format";
import type { OccupationEstimate, RadarNoticeOut } from "../api/types";

const PAGE_SIZE = 50;
// Cohorts this close get the brand-red countdown chip.
const SOON_DAYS = 14;
// Default lookahead. Also clamps far-future junk dates out of the first view.
const DEFAULT_DAYS = 180;

const HORIZONS = [
  { label: "30 days", value: 30 },
  { label: "60 days", value: 60 },
  { label: "90 days", value: 90 },
  { label: "6 months", value: 180 },
  { label: "1 year", value: 365 },
  { label: "2 years", value: 730 },
] as const;

const MIN_COHORTS = [
  { label: "Any size", value: 0 },
  { label: "50+", value: 50 },
  { label: "100+", value: 100 },
  { label: "250+", value: 250 },
  { label: "500+", value: 500 },
] as const;

/* A labelled row of pill buttons -- the radar's two view controls. */
function Pills({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { label: string; value: number }[];
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
        {label}
      </span>
      <div
        role="group"
        aria-label={label}
        className="inline-flex flex-wrap rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900"
      >
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={value === o.value}
            onClick={() => onChange(o.value)}
            className={
              "rounded-full px-3 py-1 text-xs font-medium transition-colors " +
              (value === o.value
                ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100")
            }
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** "~40 Machinists" when a count estimate exists, else "12% Machinists".
 *  Employer-filed counts are exact, so they drop the "~". */
function occupationChip(o: OccupationEstimate, filed: boolean): string {
  if (o.estimate != null && o.estimate >= 1)
    return `${filed ? "" : "~"}${fmtNum(o.estimate)} ${o.title}`;
  return `${o.pct}% ${o.title}`;
}

export function RadarPage() {
  useDocumentTitle("Upcoming layoffs radar — WARN Index");
  const navigate = useNavigate({ from: "/radar" });
  const search = useSearch({ from: "/radar" });
  // Clamp URL-supplied numbers into the API's accepted ranges so a mangled
  // link degrades to a sane view instead of a permanent 422 error banner.
  const page = Math.max(1, search.page ?? 1);
  const offset = (page - 1) * PAGE_SIZE;
  const days = Math.min(730, Math.max(1, search.days ?? DEFAULT_DAYS));
  // A shared link can carry a value outside the pill presets; show it as an
  // extra, selected pill rather than leaving the active filter invisible.
  const withCurrent = (
    opts: readonly { label: string; value: number }[],
    value: number,
    label: string,
  ) => (opts.some((o) => o.value === value) ? opts : [...opts, { label, value }]);
  const minLayoffs = Math.max(0, search.min_layoffs ?? 0);

  const apiParams = {
    state: search.state,
    closure_category: search.closure_category,
    industry: search.industry,
    subsector: search.subsector,
    min_layoffs: minLayoffs || undefined,
    days,
    limit: PAGE_SIZE,
    offset,
  };

  const query = useQuery({
    queryKey: ["radar", apiParams],
    queryFn: () => api.listRadar(apiParams),
  });

  const industriesQuery = useQuery({
    queryKey: ["stats", "industries"],
    queryFn: () => api.statsIndustries(),
  });

  const handleFilterChange = (next: FilterValues, opts?: { replace?: boolean }) => {
    navigate({
      search: (prev) => ({ ...prev, ...next, page: 1 }),
      replace: opts?.replace,
    });
  };

  const handlePageChange = (newOffset: number) => {
    navigate({
      search: (prev) => ({ ...prev, page: Math.floor(newOffset / PAGE_SIZE) + 1 }),
    });
  };

  // Sorting disabled on every column: the radar's one meaningful order is
  // soonest-effective-first (server-side); client sorting would silently
  // reshuffle only the fetched page.
  const columns = useMemo<ColumnDef<RadarNoticeOut, unknown>[]>(
    () => [
      {
        header: "Effective",
        accessorKey: "effective_date",
        enableSorting: false,
        cell: (info) => {
          const row = info.row.original;
          return (
            <Link
              to="/notices/$noticeId"
              params={{ noticeId: row.notice_id }}
              className="whitespace-nowrap font-medium text-sky-700 hover:underline dark:text-sky-400"
            >
              {fmtDate(row.effective_date)}
              <span
                className={`ml-1.5 rounded-full px-1.5 py-0.5 text-xs font-normal ${
                  row.days_until <= SOON_DAYS
                    ? "bg-brand/10 text-brand dark:bg-brand/20 dark:text-brand-dark"
                    : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                }`}
              >
                {row.days_until === 0 ? "today" : `in ${row.days_until}d`}
              </span>
            </Link>
          );
        },
      },
      {
        header: "Employer",
        accessorKey: "employer",
        enableSorting: false,
        cell: (info) => {
          const row = info.row.original;
          return (
            <span className="flex items-center gap-2.5">
              <CompanyLogo name={row.employer} companyId={row.company_id} size={24} />
              <span className="min-w-0">
                {row.company_id == null ? (
                  <span className="font-medium">{row.employer}</span>
                ) : (
                  <Link
                    to="/companies/$companyId"
                    params={{ companyId: String(row.company_id) }}
                    className="font-medium text-slate-900 hover:text-sky-700 hover:underline dark:text-slate-100 dark:hover:text-sky-400"
                  >
                    {row.employer}
                  </Link>
                )}{" "}
                <ClosureBadge category={row.closure_category} />
              </span>
            </span>
          );
        },
      },
      {
        id: "location",
        enableSorting: false,
        header: "Location",
        cell: (info) => {
          const row = info.row.original;
          const place = [row.city, row.county].filter(Boolean).join(", ");
          return (
            <span className="inline-flex items-center gap-1.5">
              <StateSilhouette code={row.state} size={16} className="shrink-0 text-slate-300 dark:text-slate-600" />
              <span>
                {place ? `${place} · ` : ""}
                {row.state}
              </span>
            </span>
          );
        },
      },
      {
        header: "Workers",
        accessorKey: "layoff_count",
        enableSorting: false,
        meta: { align: "right" },
        cell: (info) => (
          <span className="font-semibold tabular-nums">{fmtNum(info.getValue() as number | null)}</span>
        ),
      },
      {
        id: "industry",
        enableSorting: false,
        header: "Industry",
        cell: (info) => {
          const row = info.row.original;
          // No sector name also covers pseudo-codes like 999990
          // ("unclassified") — never show a raw NAICS code here.
          if (!row.naics_code || !row.sector_name)
            return (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                Industry unknown
              </span>
            );
          return row.sector_name;
        },
      },
      {
        id: "roles",
        enableSorting: false,
        header: "Likely roles (est.)",
        cell: (info) => {
          const preview = info.row.original.occupation_preview;
          if (!preview || preview.length === 0) return "—";
          const filed = info.row.original.occupation_source === "employer_filing";
          return (
            <span className="text-xs text-slate-600 dark:text-slate-400">
              {preview.map((o) => occupationChip(o, filed)).join(" · ")}
            </span>
          );
        },
      },
    ],
    [],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        kicker="Upcoming"
        title="Layoff radar"
        lede={
          <>
            WARN notices must be filed at least 60 days before separation — these layoffs
            haven&apos;t happened yet. Cohorts are listed by the date they hit the labor market,
            soonest first.
          </>
        }
        aside={
          query.data && (
            <div className="text-right">
              <div className="font-display text-3xl font-semibold tabular-nums">
                {fmtNum(query.data.total)}
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                upcoming {query.data.total === 1 ? "cohort" : "cohorts"}
              </div>
            </div>
          )
        }
      />

      <FilterBar
        values={search}
        onChange={handleFilterChange}
        showEmployer={false}
        showDates={false}
        industries={industriesQuery.data}
      />

      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <Pills
          label="Horizon"
          options={withCurrent(HORIZONS, days, `${days} days`)}
          value={days}
          onChange={(v) => navigate({ search: (prev) => ({ ...prev, days: v, page: 1 }) })}
        />
        <Pills
          label="Cohort size"
          options={withCurrent(MIN_COHORTS, minLayoffs, `${minLayoffs}+`)}
          value={minLayoffs}
          onChange={(v) =>
            navigate({ search: (prev) => ({ ...prev, min_layoffs: v || undefined, page: 1 }) })
          }
        />
      </div>

      {query.isLoading && <SkeletonTable rows={10} />}
      {query.isError && (
        <QueryError message="Error loading the radar." onRetry={() => query.refetch()} />
      )}
      {query.data && (
        <>
          <DataTable
            data={query.data.items}
            columns={columns}
            emptyMessage="No upcoming layoffs match your filters."
            emptyAction={
              <button
                type="button"
                className="btn-secondary"
                onClick={() => handleFilterChange(EMPTY_FILTERS)}
              >
                Clear all filters
              </button>
            }
          />
          <Pagination
            total={query.data.total}
            limit={query.data.limit}
            offset={query.data.offset}
            onPageChange={handlePageChange}
          />
          <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
            Likely roles apply the national BLS OEWS staffing pattern for the
            employer's industry to the reported worker count. They are a
            statistical prior from the industry's employment mix — not
            information about the actual affected roles. Notices reported
            without a dated separation are not shown here; see all notices for
            the complete record.
          </p>
        </>
      )}
    </div>
  );
}
