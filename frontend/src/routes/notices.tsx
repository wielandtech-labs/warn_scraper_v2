import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import { ActiveFilters } from "../components/ActiveFilters";
import { AlertSignup } from "../components/AlertSignup";
import { ClosureBadge } from "../components/ClosureBadge";
import { CompanyLogo } from "../components/CompanyLogo";
import { DataTable } from "../components/DataTable";
import { ExportButtons } from "../components/ExportButtons";
import { EMPTY_FILTERS, FilterBar, type FilterValues } from "../components/FilterBar";
import { NEW_NOTICE_DAYS } from "../components/NoticeList";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { Peek } from "../components/Peek";
import { CompanyPeek, StatePeek } from "../components/peeks";
import { QueryError } from "../components/QueryError";
import { SkeletonTable } from "../components/Skeleton";
import { Sparkline } from "../components/Sparkline";
import { StateSilhouette } from "../components/StateSilhouette";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useTheme } from "../hooks/useTheme";
import { daysAgoIso, fmtDate, fmtNum } from "../lib/format";
import { CHART_COLORS } from "../lib/themeColors";
import type { NoticeOut } from "../api/types";

const PAGE_SIZE = 50;

export function NoticesPage() {
  useDocumentTitle("Layoff notices — WARN Index");
  const navigate = useNavigate({ from: "/notices" });
  const search = useSearch({ from: "/notices" });
  const page = search.page ?? 1;
  const offset = (page - 1) * PAGE_SIZE;
  const sortBy = search.sort_by ?? "notice_date";
  const sortDir = search.sort_dir ?? "desc";
  const [alerting, setAlerting] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const filterCount = [
    search.state,
    search.employer,
    search.closure_category,
    search.industry,
    search.subsector,
    search.min_layoffs,
    search.after,
    search.before,
  ].filter(Boolean).length;

  // Exactly what the API call uses — keying the cache on anything more
  // (e.g. the whole search object) causes spurious misses on unrelated keys.
  const apiParams = {
    state: search.state,
    employer: search.employer,
    closure_category: search.closure_category,
    industry: search.industry,
    subsector: search.subsector,
    min_layoffs: search.min_layoffs,
    after: search.after,
    before: search.before,
    sort_by: sortBy,
    sort_dir: sortDir,
    limit: PAGE_SIZE,
    offset,
  };

  const query = useQuery({
    queryKey: ["notices", apiParams],
    queryFn: () => api.listNotices(apiParams),
  });

  // Monthly trend for the filters in force. The over-time endpoint takes
  // every filter here except employer and minimum size, so the strip hides
  // when either is set rather than show a trend for a different population.
  const { resolved } = useTheme();
  const trendable = !search.employer && !search.min_layoffs;
  const trendParams = {
    bucket: "month" as const,
    state: search.state,
    closure_category: search.closure_category,
    industry: search.industry,
    subsector: search.subsector,
    after: search.after ?? daysAgoIso(365 * 2),
    before: search.before,
  };
  const trend = useQuery({
    queryKey: ["stats", "over-time", trendParams],
    queryFn: () => api.statsOverTime(trendParams),
    enabled: trendable,
  });
  const trendValues = (trend.data ?? []).map((r) =>
    r.projected_notice_count != null ? null : r.notice_count,
  );

  const industriesQuery = useQuery({
    queryKey: ["stats", "industries"],
    queryFn: () => api.statsIndustries(),
  });

  const handleFilterChange = (next: FilterValues, opts?: { replace?: boolean }) => {
    navigate({
      search: (prev) => ({ ...prev, ...next, page: 1 }),
      // Debounced typing replaces the history entry so Back skips keystrokes.
      replace: opts?.replace,
    });
  };

  const handlePageChange = (newOffset: number) => {
    navigate({
      search: (prev) => ({ ...prev, page: Math.floor(newOffset / PAGE_SIZE) + 1 }),
    });
  };

  const handleSortChange = (colId: string, dir: "asc" | "desc") => {
    navigate({
      search: (prev) => ({ ...prev, sort_by: colId, sort_dir: dir, page: 1 }),
    });
  };

  // Inline magnitude bars scale to the largest notice on the page.
  const pageMax = Math.max(1, ...(query.data?.items ?? []).map((n) => n.layoff_count ?? 0));
  const newCutoff = daysAgoIso(NEW_NOTICE_DAYS);

  const columns = useMemo<ColumnDef<NoticeOut, unknown>[]>(
    () => [
      {
        header: "Date",
        accessorKey: "notice_date",
        cell: (info) => (
          <Link
            to="/notices/$noticeId"
            params={{ noticeId: info.row.original.notice_id }}
            // Carry the list's filters/sort/page into the detail URL so its
            // "← All notices" link can restore this exact view.
            search={(prev) => prev}
            className="inline-flex items-center gap-1.5 whitespace-nowrap font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            {((info.getValue() as string | null) ?? "") >= newCutoff && (
              <span className="h-1.5 w-1.5 rounded-full bg-brand" title="Filed in the last week" />
            )}
            {fmtDate(info.getValue() as string | null)}
          </Link>
        ),
      },
      {
        header: "State",
        accessorKey: "state",
        cell: (info) => {
          const code = info.getValue() as string;
          return (
            <Peek content={() => <StatePeek code={code} />}>
              <span className="inline-flex items-center gap-1.5">
                <StateSilhouette code={code} size={16} className="text-slate-300 dark:text-slate-600" />
                {code}
              </span>
            </Peek>
          );
        },
      },
      {
        header: "Employer",
        accessorKey: "employer",
        cell: (info) => {
          const n = info.row.original;
          const company = n.company;
          const name = info.getValue() as string;
          return (
            <span className="flex items-center gap-2.5">
              <CompanyLogo
                name={company?.name ?? name}
                companyId={company?.id}
                hasWebsite={!!company?.website}
                size={24}
              />
              <span className="min-w-0">
                {company ? (
                  <Peek content={() => <CompanyPeek id={company.id} name={company.name} />}>
                    <Link
                      to="/companies/$companyId"
                      params={{ companyId: String(company.id) }}
                      className="font-medium text-slate-900 hover:text-sky-700 hover:underline dark:text-slate-100 dark:hover:text-sky-400"
                    >
                      {name}
                    </Link>
                  </Peek>
                ) : (
                  <span className="font-medium">{name}</span>
                )}{" "}
                <ClosureBadge category={n.closure_category} />
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
          const loc = info.row.original.location;
          if (!loc) return "—";
          return [loc.city, loc.county].filter(Boolean).join(", ") || "—";
        },
      },
      {
        header: "Layoffs",
        accessorKey: "layoff_count",
        meta: { align: "right" },
        cell: (info) => {
          const v = info.getValue() as number | null;
          return (
            <span className="inline-flex items-center justify-end gap-2 tabular-nums">
              {v != null && (
                <span
                  aria-hidden
                  className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 sm:block dark:bg-slate-800"
                >
                  <span
                    className="block h-full rounded-full bg-brand/70"
                    style={{ width: `${Math.max(4, (v / pageMax) * 100)}%` }}
                  />
                </span>
              )}
              <span className="font-medium">{fmtNum(v)}</span>
            </span>
          );
        },
      },
      {
        header: "Effective",
        accessorKey: "effective_date",
        cell: (info) => (
          <span className="whitespace-nowrap text-slate-600 dark:text-slate-400">
            {fmtDate(info.getValue() as string | null)}
          </span>
        ),
      },
    ],
    [pageMax, newCutoff],
  );

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Every filing · updated daily"
        title="Layoff notices"
        lede={
          query.data ? (
            <>
              <span className="font-semibold text-slate-900 dark:text-slate-100">
                {fmtNum(query.data.total)}
              </span>{" "}
              WARN Act notices {filterCount ? "match these filters" : "across every state we track"}.
              <span className="hidden sm:inline"> Hover a company or state for its history.</span>
            </>
          ) : (
            "Every advance-notice filing from state WARN Act listings."
          )
        }
        aside={
          trendable && trendValues.length > 1 ? (
            <div className="w-56">
              <div className="flex items-baseline justify-between text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
                <span>Notices per month</span>
                {!search.after && <span>2 yrs</span>}
              </div>
              <Sparkline
                values={trendValues}
                color={CHART_COLORS[resolved].notices}
                height={40}
                className="mt-1"
              />
            </div>
          ) : undefined
        }
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ActiveFilters
          values={search}
          industries={industriesQuery.data}
          onChange={(v) => handleFilterChange(v)}
        />
        <ExportButtons
          basePath="/api/notices/export"
          params={{
            state: search.state,
            employer: search.employer,
            closure_category: search.closure_category,
            industry: search.industry,
            subsector: search.subsector,
            min_layoffs: search.min_layoffs,
            after: search.after,
            before: search.before,
          }}
        />
      </div>
      {/* On phones the full filter form would fill the first screen before
          a single result; it sits behind a toggle there (chips above still
          show what is applied). Always shown from sm up. */}
      <button
        type="button"
        className="btn-secondary w-full sm:hidden"
        aria-expanded={showFilters}
        onClick={() => setShowFilters((v) => !v)}
      >
        {showFilters ? "Hide filters" : `Filters${filterCount ? ` (${filterCount})` : ""}`}
      </button>
      <div className={showFilters ? "" : "hidden sm:block"}>
        <FilterBar
          values={search}
          onChange={handleFilterChange}
          industries={industriesQuery.data}
        />
      </div>

      <div>
        {alerting ? (
          // Seeded from the filters on screen, so the alert matches the list
          // the reader is looking at (dates excluded — an alert is forward-looking).
          <AlertSignup
            initialFilters={{
              state: search.state,
              industry: search.industry,
              subsector: search.subsector,
              employer_query: search.employer,
              closure_category: search.closure_category,
              min_layoffs: search.min_layoffs,
            }}
            defaultOpen
          />
        ) : (
          <button type="button" className="btn-secondary" onClick={() => setAlerting(true)}>
            Alert me about these results
          </button>
        )}
      </div>

      {query.isLoading && <SkeletonTable rows={10} />}
      {query.isError && (
        <QueryError message="Error loading notices." onRetry={() => query.refetch()} />
      )}
      {query.data && (
        <>
          <DataTable
            data={query.data.items}
            columns={columns}
            emptyMessage="No notices match your filters."
            emptyAction={
              <button
                type="button"
                className="btn-secondary"
                onClick={() => handleFilterChange(EMPTY_FILTERS)}
              >
                Clear all filters
              </button>
            }
            sortBy={sortBy}
            sortDir={sortDir}
            onSortChange={handleSortChange}
          />
          <Pagination
            total={query.data.total}
            limit={query.data.limit}
            offset={query.data.offset}
            onPageChange={handlePageChange}
          />
        </>
      )}
    </div>
  );
}
