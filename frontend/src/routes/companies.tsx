import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import { Pagination } from "../components/Pagination";
import type { CompanyOut } from "../api/types";

const PAGE_SIZE = 50;

export function CompaniesPage() {
  const navigate = useNavigate({ from: "/companies" });
  const search = useSearch({ from: "/companies" });
  const page = search.page ?? 1;
  const offset = (page - 1) * PAGE_SIZE;

  const query = useQuery({
    queryKey: ["companies", search, offset],
    queryFn: () =>
      api.listCompanies({
        enriched:
          search.enriched === "true" ? true : search.enriched === "false" ? false : undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  const setEnriched = (val: "true" | "false" | undefined) => {
    navigate({ search: () => ({ enriched: val, page: 1 }) });
  };

  const handlePageChange = (newOffset: number) => {
    navigate({
      search: (prev) => ({ ...prev, page: Math.floor(newOffset / PAGE_SIZE) + 1 }),
    });
  };

  const columns = useMemo<ColumnDef<CompanyOut, unknown>[]>(
    () => [
      {
        header: "Name",
        accessorKey: "name",
        cell: (info) => (
          <Link
            to="/companies/$companyId"
            params={{ companyId: String(info.row.original.id) }}
            className="font-medium text-sky-700 hover:underline"
          >
            {info.getValue() as string}
          </Link>
        ),
      },
      {
        header: "SIC",
        cell: (info) => {
          const c = info.row.original;
          if (!c.sic_code) return "—";
          return (
            <>
              <span className="font-mono">{c.sic_code}</span>
              {c.sic_desc && <span className="ml-2 text-slate-500">{c.sic_desc}</span>}
            </>
          );
        },
      },
      {
        header: "Website",
        accessorKey: "website",
        cell: (info) => {
          const url = info.getValue() as string | null;
          if (!url) return "—";
          return (
            <a className="text-sky-700 hover:underline" href={url} target="_blank" rel="noreferrer">
              {url.replace(/^https?:\/\//, "")}
            </a>
          );
        },
      },
      {
        header: "Status",
        accessorKey: "enriched_at",
        cell: (info) => {
          const c = info.row.original;
          if (!c.enriched_at) return <span className="badge-slate">Pending</span>;
          const conf = c.enrichment_confidence != null ? Number(c.enrichment_confidence) : null;
          if (conf != null && conf >= 0.7) {
            return <span className="badge-green">Enriched · {conf.toFixed(2)}</span>;
          }
          return <span className="badge-amber">Low confidence · {conf?.toFixed(2) ?? "?"}</span>;
        },
      },
    ],
    [],
  );

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Companies</h1>
        <div className="flex gap-1">
          <FilterChip active={!search.enriched} onClick={() => setEnriched(undefined)} label="All" />
          <FilterChip
            active={search.enriched === "true"}
            onClick={() => setEnriched("true")}
            label="Enriched"
          />
          <FilterChip
            active={search.enriched === "false"}
            onClick={() => setEnriched("false")}
            label="Pending"
          />
        </div>
      </div>

      {query.isLoading && <div className="card text-sm text-slate-500">Loading…</div>}
      {query.data && (
        <>
          <DataTable data={query.data.items} columns={columns} emptyMessage="No companies." />
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

function FilterChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={
        active
          ? "rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white"
          : "rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
      }
    >
      {label}
    </button>
  );
}
