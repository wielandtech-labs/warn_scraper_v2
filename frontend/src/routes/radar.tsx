import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import { EMPTY_FILTERS, FilterBar, type FilterValues } from "../components/FilterBar";
import { Pagination } from "../components/Pagination";
import { QueryError } from "../components/QueryError";
import { SkeletonTable } from "../components/Skeleton";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum } from "../lib/format";
import type { OccupationEstimate, RadarNoticeOut } from "../api/types";

const PAGE_SIZE = 50;
// Default lookahead. Also clamps far-future junk dates out of the first view.
const DEFAULT_DAYS = 180;

const HORIZONS = [
  { label: "Next 30 days", days: 30 },
  { label: "Next 60 days", days: 60 },
  { label: "Next 90 days", days: 90 },
  { label: "Next 6 months", days: 180 },
  { label: "Next year", days: 365 },
  { label: "Next 2 years", days: 730 },
] as const;

const MIN_COHORTS = [
  { label: "Any size", value: 0 },
  { label: "50+ workers", value: 50 },
  { label: "100+ workers", value: 100 },
  { label: "250+ workers", value: 250 },
  { label: "500+ workers", value: 500 },
] as const;

/** "~40 Machinists" when a count estimate exists, else "12% Machinists".
 *  Employer-filed counts are exact, so they drop the "~". */
function occupationChip(o: OccupationEstimate, filed: boolean): string {
  if (o.estimate != null && o.estimate >= 1)
    return `${filed ? "" : "~"}${fmtNum(o.estimate)} ${o.title}`;
  return `${o.pct}% ${o.title}`;
}

export function RadarPage() {
  useDocumentTitle("Upcoming layoffs radar — WARN Tracker");
  const navigate = useNavigate({ from: "/radar" });
  const search = useSearch({ from: "/radar" });
  // Clamp URL-supplied numbers into the API's accepted ranges so a mangled
  // link degrades to a sane view instead of a permanent 422 error banner.
  const page = Math.max(1, search.page ?? 1);
  const offset = (page - 1) * PAGE_SIZE;
  const days = Math.min(730, Math.max(1, search.days ?? DEFAULT_DAYS));
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
              className="font-medium text-sky-700 hover:underline dark:text-sky-400"
            >
              {fmtDate(row.effective_date)}
              <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-600 dark:bg-slate-800 dark:text-slate-400">
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
          if (row.company_id == null)
            return <span className="font-medium">{row.employer}</span>;
          return (
            <Link
              to="/companies/$companyId"
              params={{ companyId: String(row.company_id) }}
              className="font-medium text-sky-700 hover:underline dark:text-sky-400"
            >
              {row.employer}
            </Link>
          );
        },
      },
      {
        id: "location",
        enableSorting: false,
        header: "Location",
        cell: (info) => {
          const row = info.row.original;
          return [row.city, row.county].filter(Boolean).join(", ") || row.state;
        },
      },
      { header: "State", accessorKey: "state", enableSorting: false },
      {
        header: "Workers",
        accessorKey: "layoff_count",
        enableSorting: false,
        cell: (info) => fmtNum(info.getValue() as number | null),
      },
      {
        header: "Type",
        accessorKey: "closure_category",
        enableSorting: false,
        cell: (info) => (info.getValue() as string | null) ?? "—",
      },
      {
        id: "industry",
        enableSorting: false,
        header: "Industry",
        cell: (info) => {
          const row = info.row.original;
          if (!row.naics_code)
            return (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                Industry unknown
              </span>
            );
          return row.sector_name ?? row.naics_code;
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

  const selectClass =
    "rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
  const labelClass =
    "text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400";

  return (
    <div>
      <div className="mb-3">
        <h1 className="text-2xl font-semibold">Radar</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          WARN notices must be filed at least 60 days before separation — these
          layoffs haven't happened yet. Cohorts are listed by the date they hit
          the labor market, soonest first.
        </p>
      </div>

      <FilterBar
        values={search}
        onChange={handleFilterChange}
        showEmployer={false}
        showDates={false}
        industries={industriesQuery.data}
      />

      <div className="card mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Horizon</span>
          <select
            className={selectClass}
            value={days}
            onChange={(e) =>
              navigate({ search: (prev) => ({ ...prev, days: Number(e.target.value), page: 1 }) })
            }
          >
            {HORIZONS.map((h) => (
              <option key={h.days} value={h.days}>
                {h.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelClass}>Min cohort size</span>
          <select
            className={selectClass}
            value={minLayoffs}
            onChange={(e) =>
              navigate({
                search: (prev) => ({
                  ...prev,
                  min_layoffs: Number(e.target.value) || undefined,
                  page: 1,
                }),
              })
            }
          >
            {MIN_COHORTS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
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
