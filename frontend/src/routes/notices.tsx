import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import { FilterBar, type FilterValues } from "../components/FilterBar";
import { Pagination } from "../components/Pagination";
import { fmtDate, fmtNum } from "../lib/format";
import type { NoticeOut } from "../api/types";

const PAGE_SIZE = 50;

export function NoticesPage() {
  const navigate = useNavigate({ from: "/notices" });
  const search = useSearch({ from: "/notices" });
  const page = search.page ?? 1;
  const offset = (page - 1) * PAGE_SIZE;

  const query = useQuery({
    queryKey: ["notices", search, offset],
    queryFn: () =>
      api.listNotices({
        state: search.state,
        employer: search.employer,
        after: search.after,
        before: search.before,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  const handleFilterChange = (next: FilterValues) => {
    navigate({
      search: () => ({ ...next, page: 1 }),
    });
  };

  const handlePageChange = (newOffset: number) => {
    navigate({
      search: (prev) => ({ ...prev, page: Math.floor(newOffset / PAGE_SIZE) + 1 }),
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
            className="font-medium text-sky-700 hover:underline"
          >
            {info.getValue() as string}
          </Link>
        ),
      },
      {
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
      <h1 className="mb-3 text-2xl font-semibold">Notices</h1>
      <FilterBar values={search} onChange={handleFilterChange} />

      {query.isLoading && <div className="card text-center text-sm text-slate-500">Loading…</div>}
      {query.isError && (
        <div className="card text-center text-sm text-red-600">
          Error loading notices.
        </div>
      )}
      {query.data && (
        <>
          <DataTable
            data={query.data.items}
            columns={columns}
            emptyMessage="No notices match your filters."
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
