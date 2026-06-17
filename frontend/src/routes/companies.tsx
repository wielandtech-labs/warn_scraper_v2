import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import { ExportButtons } from "../components/ExportButtons";
import { Pagination } from "../components/Pagination";
import type { CompanyOut, ParentGroupStat } from "../api/types";
import { fmtNum } from "../lib/format";

const PAGE_SIZE = 50;

// enrichment_source → human label. Confidence alone is misleading: a "Web"
// row is usually just a website found by the LLM, while "D&B" is a full record.
export const SOURCE_LABEL: Record<string, string> = {
  provider: "D&B",
  edgar: "SEC",
  claude: "Web",
};

export function CompaniesPage() {
  const navigate = useNavigate({ from: "/companies" });
  const search = useSearch({ from: "/companies" });
  const view = search.view ?? "companies";

  const setView = (next: "companies" | "families") => {
    navigate({
      search: (prev) => ({
        ...prev,
        view: next === "families" ? "families" : undefined,
        page: 1,
      }),
    });
  };

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">
          {view === "families" ? "Corporate families" : "Companies"}
        </h1>
        <div className="flex gap-1 rounded-md border border-slate-300 p-0.5">
          <ViewTab active={view === "companies"} onClick={() => setView("companies")} label="Companies" />
          <ViewTab
            active={view === "families"}
            onClick={() => setView("families")}
            label="Corporate families"
          />
        </div>
      </div>

      {view === "families" ? <FamiliesView /> : <CompaniesView />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Companies list view
// ---------------------------------------------------------------------------

function CompaniesView() {
  const navigate = useNavigate({ from: "/companies" });
  const search = useSearch({ from: "/companies" });
  const page = search.page ?? 1;
  const offset = (page - 1) * PAGE_SIZE;
  const sortBy = search.sort_by ?? "name";
  const sortDir = search.sort_dir ?? "asc";

  // Exactly what the API call uses — keying the cache on anything more
  // (e.g. the whole search object) causes spurious misses on unrelated keys.
  const apiParams = {
    enriched:
      search.enriched === "true" ? true : search.enriched === "false" ? false : undefined,
    has_duns: search.duns === "true" ? true : undefined,
    industry: search.industry,
    subsector: search.subsector,
    sort_by: sortBy,
    sort_dir: sortDir,
    limit: PAGE_SIZE,
    offset,
  };

  const query = useQuery({
    queryKey: ["companies", apiParams],
    queryFn: () => api.listCompanies(apiParams),
  });

  const industriesQuery = useQuery({
    queryKey: ["stats", "industries"],
    queryFn: () => api.statsIndustries(),
  });

  // Subsectors of the currently-selected sector (drives the drill-down dropdown).
  const selectedSubsectors =
    industriesQuery.data?.find((i) => i.sector === search.industry)?.subsectors ?? [];

  // One status chip group: enriched and duns are mutually exclusive choices.
  const setEnriched = (val: "true" | "false" | undefined) => {
    navigate({ search: (prev) => ({ ...prev, enriched: val, duns: undefined, page: 1 }) });
  };

  const setDuns = () => {
    navigate({ search: (prev) => ({ ...prev, enriched: undefined, duns: "true", page: 1 }) });
  };

  // Changing the sector clears any subsector selection.
  const setIndustry = (val: string | undefined) => {
    navigate({ search: (prev) => ({ ...prev, industry: val, subsector: undefined, page: 1 }) });
  };

  const setSubsector = (val: string | undefined) => {
    navigate({ search: (prev) => ({ ...prev, subsector: val, page: 1 }) });
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

  const columns = useMemo<ColumnDef<CompanyOut, unknown>[]>(
    () => [
      {
        header: "Name",
        accessorKey: "name",
        cell: (info) => (
          <Link
            to="/companies/$companyId"
            params={{ companyId: String(info.row.original.id) }}
            // Carry the list's filters/sort/page into the detail URL so its
            // "← All companies" link can restore this exact view.
            search={(prev) => prev}
            className="font-medium text-sky-700 hover:underline"
          >
            {info.getValue() as string}
          </Link>
        ),
      },
      {
        header: "Workers affected",
        accessorKey: "layoff_total",
        cell: (info) => (
          <div className="text-right tabular-nums">
            {fmtNum(info.getValue() as number | null)}
          </div>
        ),
      },
      {
        id: "sic",
        enableSorting: false,
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
        enableSorting: false,
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
        // Sorts server-side by confidence — what the badge actually displays.
        id: "enrichment_confidence",
        header: "Status",
        cell: (info) => {
          const c = info.row.original;
          if (!c.enriched_at) return <span className="badge-slate">Pending</span>;
          const conf = c.enrichment_confidence != null ? Number(c.enrichment_confidence) : null;
          const label = SOURCE_LABEL[c.enrichment_source ?? ""] ?? "Enriched";
          // Confidence means "right company identified", not data quality —
          // only a D&B (provider) row carries the full record, so only it
          // earns the green badge.
          if (c.enrichment_source === "provider") {
            return <span className="badge-green">{label} · {conf?.toFixed(2) ?? "?"}</span>;
          }
          return <span className="badge-amber">{label} · {conf?.toFixed(2) ?? "?"}</span>;
        },
      },
    ],
    [],
  );

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-3">
        <select
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          value={search.industry || ""}
          onChange={(e) => setIndustry(e.target.value || undefined)}
        >
          <option value="">All industries</option>
          {(industriesQuery.data ?? []).map((i) => (
            <option key={i.sector} value={i.sector}>
              {i.name} ({i.notice_count})
            </option>
          ))}
        </select>
        {selectedSubsectors.length > 0 && (
          <select
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={search.subsector || ""}
            onChange={(e) => setSubsector(e.target.value || undefined)}
          >
            <option value="">All subsectors</option>
            {selectedSubsectors.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name} ({s.notice_count})
              </option>
            ))}
          </select>
        )}
        <div className="flex gap-1">
          <FilterChip
            active={!search.enriched && !search.duns}
            onClick={() => setEnriched(undefined)}
            label="All"
          />
          <FilterChip
            active={search.enriched === "true"}
            onClick={() => setEnriched("true")}
            label="Enriched"
          />
          <FilterChip active={search.duns === "true"} onClick={setDuns} label="DUNS" />
          <FilterChip
            active={search.enriched === "false"}
            onClick={() => setEnriched("false")}
            label="Pending"
          />
        </div>
        <ExportButtons
          basePath="/api/companies/export"
          params={{
            enriched: search.enriched,
            has_duns: search.duns === "true" ? true : undefined,
            industry: search.industry,
            subsector: search.subsector,
          }}
        />
      </div>

      {query.isLoading && <div className="card text-sm text-slate-500">Loading…</div>}
      {query.data && (
        <>
          <DataTable
            data={query.data.items}
            columns={columns}
            emptyMessage="No companies."
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

// ---------------------------------------------------------------------------
// Corporate families view (formerly the standalone /families page)
// ---------------------------------------------------------------------------

function FamiliesView() {
  const query = useQuery({
    queryKey: ["stats", "by-parent-group"],
    queryFn: () => api.statsByParentGroup({ limit: 50 }),
  });

  // No onSortChange → DataTable sorts the 50 rows client-side.
  const columns = useMemo<ColumnDef<ParentGroupStat, unknown>[]>(
    () => [
      {
        header: "Family (largest member)",
        accessorKey: "representative_company_name",
        cell: (info) => (
          <Link
            to="/companies/$companyId"
            params={{ companyId: String(info.row.original.representative_company_id) }}
            search={(prev) => prev}
            className="font-medium text-sky-700 hover:underline"
          >
            {info.getValue() as string}
          </Link>
        ),
      },
      {
        header: "Members",
        accessorKey: "member_count",
        cell: (info) => (
          <div className="text-right tabular-nums">{fmtNum(info.getValue() as number)}</div>
        ),
      },
      {
        header: "Notices",
        accessorKey: "notice_count",
        cell: (info) => (
          <div className="text-right tabular-nums">{fmtNum(info.getValue() as number)}</div>
        ),
      },
      {
        header: "Workers affected",
        accessorKey: "layoff_total",
        cell: (info) => (
          <div className="text-right font-medium tabular-nums">
            {fmtNum(info.getValue() as number)}
          </div>
        ),
      },
    ],
    [],
  );

  return (
    <div>
      <p className="mb-3 text-sm text-slate-500">
        Companies grouped into corporate families, ranked by total layoffs across all
        their subsidiaries. Each family is labeled by its largest member, and the
        list grows as enrichment links subsidiaries to a shared parent.
      </p>

      {query.isLoading && <div className="card text-sm text-slate-500">Loading…</div>}
      {query.data && (
        <DataTable
          data={query.data}
          columns={columns}
          emptyMessage="No corporate families found yet."
        />
      )}
    </div>
  );
}

function ViewTab({
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
          ? "rounded px-3 py-1 text-sm font-medium bg-sky-600 text-white"
          : "rounded px-3 py-1 text-sm font-medium text-slate-600 hover:bg-slate-100"
      }
    >
      {label}
    </button>
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
