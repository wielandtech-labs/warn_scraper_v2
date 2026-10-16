import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";

import { api } from "../api/client";
import { CompanyLogo } from "../components/CompanyLogo";
import { DataTable } from "../components/DataTable";
import { ExportButtons } from "../components/ExportButtons";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { Peek } from "../components/Peek";
import { CompanyPeek } from "../components/peeks";
import { QueryError } from "../components/QueryError";
import { SkeletonTable } from "../components/Skeleton";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import type { CompanyOut, ParentGroupStat } from "../api/types";
import { fmtNum, SOURCE_LABEL } from "../lib/format";

const PAGE_SIZE = 50;

export function CompaniesPage() {
  useDocumentTitle("Companies & corporate families — WARN Index");
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
    <div className="space-y-5">
      <PageHeader
        kicker="Employers"
        title={view === "families" ? "Corporate families" : "Companies"}
        lede={
          view === "families"
            ? "Companies grouped into corporate families, ranked by total layoffs across all their subsidiaries."
            : "Every employer that has filed a WARN notice, with filings under variant names rolled up into one record."
        }
        aside={
          <div
            role="group"
            aria-label="View"
            className="inline-flex rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900"
          >
            <ViewTab active={view === "companies"} onClick={() => setView("companies")} label="Companies" />
            <ViewTab
              active={view === "families"}
              onClick={() => setView("families")}
              label="Corporate families"
            />
          </div>
        }
      />

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
  const sortBy = search.sort_by ?? "layoff_total";
  const sortDir = search.sort_dir ?? "desc";

  // Exactly what the API call uses — keying the cache on anything more
  // (e.g. the whole search object) causes spurious misses on unrelated keys.
  const apiParams = {
    enriched:
      search.enriched === "true" ? true : search.enriched === "false" ? false : undefined,
    has_unique_id: search.unique_id === "true" ? true : undefined,
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

  // One status chip group: enriched and unique_id are mutually exclusive choices.
  const setEnriched = (val: "true" | "false" | undefined) => {
    navigate({ search: (prev) => ({ ...prev, enriched: val, unique_id: undefined, page: 1 }) });
  };

  const setUniqueId = () => {
    navigate({ search: (prev) => ({ ...prev, enriched: undefined, unique_id: "true", page: 1 }) });
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

  // Inline magnitude bars scale to the largest company on the page.
  const pageMax = Math.max(1, ...(query.data?.items ?? []).map((c) => c.layoff_total ?? 0));

  const columns = useMemo<ColumnDef<CompanyOut, unknown>[]>(
    () => [
      {
        header: "Name",
        accessorKey: "name",
        cell: (info) => (
          <Peek
            content={() => (
              <CompanyPeek id={info.row.original.id} name={info.getValue() as string} />
            )}
          >
            <Link
              to="/companies/$companyId"
              params={{ companyId: String(info.row.original.id) }}
              // Carry the list's filters/sort/page into the detail URL so its
              // "← All companies" link can restore this exact view.
              search={(prev) => prev}
              className="inline-flex items-center gap-2.5 font-medium text-sky-700 hover:underline dark:text-sky-400"
            >
              <CompanyLogo
                name={info.getValue() as string}
                companyId={info.row.original.id}
                hasWebsite={!!info.row.original.website}
                size={24}
              />
              {info.getValue() as string}
            </Link>
          </Peek>
        ),
      },
      {
        header: "Workers affected",
        accessorKey: "layoff_total",
        meta: { align: "right" },
        cell: (info) => (
          <WorkersCell value={info.getValue() as number | null} max={pageMax} />
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
              {c.sic_desc && <span className="ml-2 text-slate-500 dark:text-slate-400">{c.sic_desc}</span>}
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
            <a className="text-sky-700 hover:underline dark:text-sky-400" href={url} target="_blank" rel="noreferrer">
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
          // only a provider row carries the full record, so only it
          // earns the green badge.
          if (c.enrichment_source === "provider") {
            return <span className="badge-green">{label} · {conf?.toFixed(2) ?? "?"}</span>;
          }
          return <span className="badge-amber">{label} · {conf?.toFixed(2) ?? "?"}</span>;
        },
      },
    ],
    [pageMax],
  );

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-3">
        <select
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
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
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
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
            active={!search.enriched && !search.unique_id}
            onClick={() => setEnriched(undefined)}
            label="All"
          />
          <FilterChip
            active={search.enriched === "true"}
            onClick={() => setEnriched("true")}
            label="Enriched"
          />
          <FilterChip active={search.unique_id === "true"} onClick={setUniqueId} label="Has ID" />
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
            has_unique_id: search.unique_id === "true" ? true : undefined,
            industry: search.industry,
            subsector: search.subsector,
          }}
        />
      </div>

      {query.isLoading && <SkeletonTable rows={10} />}
      {query.isError && (
        <QueryError message="Error loading companies." onRetry={() => query.refetch()} />
      )}
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

  const familyMax = Math.max(1, ...(query.data ?? []).map((f) => f.layoff_total));

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
            className="inline-flex items-center gap-2.5 font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            <CompanyLogo
              name={info.getValue() as string}
              companyId={info.row.original.representative_company_id}
              size={24}
            />
            {info.getValue() as string}
          </Link>
        ),
      },
      {
        header: "Members",
        accessorKey: "member_count",
        meta: { align: "right" },
        cell: (info) => <span className="tabular-nums">{fmtNum(info.getValue() as number)}</span>,
      },
      {
        header: "Notices",
        accessorKey: "notice_count",
        meta: { align: "right" },
        cell: (info) => <span className="tabular-nums">{fmtNum(info.getValue() as number)}</span>,
      },
      {
        header: "Workers affected",
        accessorKey: "layoff_total",
        meta: { align: "right" },
        cell: (info) => (
          <WorkersCell value={info.getValue() as number} max={familyMax} />
        ),
      },
    ],
    [familyMax],
  );

  return (
    <div>
      <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
        Each family is labeled by its largest member; the list grows as enrichment
        links subsidiaries to a shared parent.
      </p>

      {query.isLoading && <SkeletonTable rows={10} />}
      {query.isError && (
        <QueryError
          message="Error loading corporate families."
          onRetry={() => query.refetch()}
        />
      )}
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

/* Workers affected with an inline bar on the table's shared scale. */
function WorkersCell({ value, max }: { value: number | null; max: number }) {
  return (
    <span className="inline-flex items-center justify-end gap-2 tabular-nums">
      {value != null && (
        <span
          aria-hidden
          className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 sm:block dark:bg-slate-800"
        >
          <span
            className="block h-full rounded-full bg-brand/70"
            style={{ width: `${Math.max(2, (value / max) * 100)}%` }}
          />
        </span>
      )}
      {fmtNum(value)}
    </span>
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
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={
        "rounded-full px-3 py-1 text-xs font-medium transition-colors " +
        (active
          ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
          : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100")
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
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={
        "rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
        (active
          ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
          : "border-slate-300 text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800")
      }
    >
      {label}
    </button>
  );
}
