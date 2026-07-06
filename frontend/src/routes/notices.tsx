import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import { ExportButtons } from "../components/ExportButtons";
import { EMPTY_FILTERS, FilterBar, type FilterValues } from "../components/FilterBar";
import { Pagination } from "../components/Pagination";
import { QueryError } from "../components/QueryError";
import { SkeletonTable } from "../components/Skeleton";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum } from "../lib/format";
import type { NoticeOut } from "../api/types";

const PAGE_SIZE = 50;

export function NoticesPage() {
  useDocumentTitle("Layoff notices — WARN Tracker");
  const navigate = useNavigate({ from: "/notices" });
  const search = useSearch({ from: "/notices" });
  const page = search.page ?? 1;
  const offset = (page - 1) * PAGE_SIZE;
  const sortBy = search.sort_by ?? "notice_date";
  const sortDir = search.sort_dir ?? "desc";

  // Exactly what the API call uses — keying the cache on anything more
  // (e.g. the whole search object) causes spurious misses on unrelated keys.
  const apiParams = {
    state: search.state,
    employer: search.employer,
    closure_category: search.closure_category,
    industry: search.industry,
    subsector: search.subsector,
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

  const columns = useMemo<ColumnDef<NoticeOut, unknown>[]>(
    () => [
      {
        header: "Date",
        accessorKey: "notice_date",
        cell: (info) => fmtDate(info.getValue() as string | null),
      },
      { header: "State", accessorKey: "state" },
      {
        header: "Employer",
        accessorKey: "employer",
        cell: (info) => (
          <Link
            to="/notices/$noticeId"
            params={{ noticeId: info.row.original.notice_id }}
            // Carry the list's filters/sort/page into the detail URL so its
            // "← All notices" link can restore this exact view.
            search={(prev) => prev}
            className="font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            {info.getValue() as string}
          </Link>
        ),
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
        cell: (info) => fmtNum(info.getValue() as number | null),
      },
      {
        header: "Effective",
        accessorKey: "effective_date",
        cell: (info) => fmtDate(info.getValue() as string | null),
      },
    ],
    [],
  );

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Notices</h1>
        <ExportButtons
          basePath="/api/notices/export"
          params={{
            state: search.state,
            employer: search.employer,
            closure_category: search.closure_category,
            industry: search.industry,
            subsector: search.subsector,
            after: search.after,
            before: search.before,
          }}
        />
      </div>
      <FilterBar
        values={search}
        onChange={handleFilterChange}
        industries={industriesQuery.data}
      />

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
