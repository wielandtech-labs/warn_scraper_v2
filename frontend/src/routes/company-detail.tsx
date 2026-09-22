import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { api } from "../api/client";
import { SkeletonBlock } from "../components/Skeleton";
import { useAuth } from "../hooks/useAuth";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum } from "../lib/format";
import { SOURCE_LABEL } from "./companies";

export function CompanyDetail() {
  const { companyId } = useParams({ from: "/companies/$companyId" });
  const id = Number(companyId);

  const company = useQuery({
    queryKey: ["company", id],
    queryFn: () => api.getCompany(id),
    enabled: !Number.isNaN(id),
  });

  const notices = useQuery({
    queryKey: ["company", id, "notices"],
    queryFn: () => api.listCompanyNotices(id, { limit: 50 }),
    enabled: !Number.isNaN(id),
  });

  const family = useQuery({
    queryKey: ["company", id, "family"],
    queryFn: () => api.getCompanyFamily(id),
    enabled: !Number.isNaN(id),
  });

  const members = useQuery({
    queryKey: ["company", id, "members"],
    queryFn: () => api.getCompanyMembers(id),
    enabled: !Number.isNaN(id),
  });

  const auth = useAuth();
  const isAdmin = auth.data?.role === "admin";
  const queryClient = useQueryClient();
  const unmerge = useMutation({
    mutationFn: api.adminUnmergeCompany,
    // Rollups change everywhere (this page, lists, top employers).
    onSuccess: () => queryClient.invalidateQueries(),
  });

  useDocumentTitle(
    company.data ? `${company.data.name} — WARN Tracker` : undefined,
  );

  if (Number.isNaN(id)) {
    return <div className="card text-red-600 dark:text-red-400">Invalid company ID.</div>;
  }
  if (company.isLoading) {
    return (
      <div className="card space-y-3">
        <SkeletonBlock className="h-7 w-2/3" />
        <SkeletonBlock className="h-4 w-1/3" />
        <SkeletonBlock className="h-24 w-full" />
      </div>
    );
  }
  if (company.isError || !company.data) {
    return (
      <div className="card text-red-600 dark:text-red-400">
        Company not found.{" "}
        <Link to="/companies" search={(prev) => prev} className="font-medium underline">
          ← Back
        </Link>
      </div>
    );
  }

  const c = company.data;

  return (
    <div className="space-y-4">
      <div>
        {/* The detail URL carries the list's search params (see router.tsx);
            re-applying them restores the exact filters/sort/page. */}
        <Link to="/companies" search={(prev) => prev} className="text-sm text-sky-700 hover:underline dark:text-sky-400">
          ← All companies
        </Link>
      </div>
      <div className="card">
        <h1 className="text-2xl font-semibold">{c.name}</h1>
        {c.canonical_company_id != null && (
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            This record is counted under{" "}
            <Link
              to="/companies/$companyId"
              params={{ companyId: String(c.canonical_company_id) }}
              search={(prev) => prev}
              className="text-sky-700 hover:underline dark:text-sky-400"
            >
              its main company record
            </Link>
            .
          </p>
        )}
        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          {c.website && (
            <Item
              label="Website"
              value={
                <a className="text-sky-700 hover:underline dark:text-sky-400" href={c.website} target="_blank" rel="noreferrer">
                  {c.website}
                </a>
              }
            />
          )}
          <Item label="SIC" value={c.sic_code ? `${c.sic_code} · ${c.sic_desc ?? ""}` : "—"} />
          {/* provider fields are present in the payload only for paid/admin
              sessions — render whatever the API returned, no role logic here. */}
          {c.duns != null && <Item label="DUNS" value={c.duns} />}
          {c.employee_count != null && (
            <Item label="Employees" value={fmtNum(c.employee_count)} />
          )}
          {c.parent_company_name != null && (
            <Item
              label="Parent"
              value={
                c.parent_duns != null
                  ? `${c.parent_company_name} · DUNS ${c.parent_duns}`
                  : c.parent_company_name
              }
            />
          )}
          {c.parent_company_name == null && c.parent_duns != null && (
            <Item label="Parent DUNS" value={c.parent_duns} />
          )}
          {c.global_ultimate_name != null && (
            <Item label="Global ultimate" value={c.global_ultimate_name} />
          )}
          {c.hq_address != null && <Item label="HQ address" value={c.hq_address} />}
          <Item
            label="Enriched"
            value={
              c.enriched_at
                ? `${fmtDate(c.enriched_at)} · ${
                    SOURCE_LABEL[c.enrichment_source ?? ""] ?? "unknown source"
                  } · confidence ${
                    c.enrichment_confidence != null
                      ? Number(c.enrichment_confidence).toFixed(2)
                      : "?"
                  }`
                : "Not yet enriched"
            }
          />
        </dl>
      </div>

      {family.data && family.data.length >= 2 && (
        <section>
          <h2 className="mb-2 text-lg font-semibold">
            Corporate family ({family.data.length})
          </h2>
          <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">
            Companies in the same corporate family, with layoffs rolled up across
            each one.
          </p>
          <div className="card divide-y divide-slate-100 p-0 dark:divide-slate-800">
            {family.data.map((m) => (
              <Link
                key={m.company_id}
                to="/companies/$companyId"
                params={{ companyId: String(m.company_id) }}
                search={(prev) => prev}
                className={`flex items-baseline justify-between gap-4 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
                  m.is_self ? "bg-sky-50 dark:bg-sky-950" : ""
                }`}
              >
                <div className="text-sm font-medium">
                  {m.name}
                  {m.is_self && (
                    <span className="ml-2 text-xs font-normal text-sky-700 dark:text-sky-400">
                      this company
                    </span>
                  )}
                </div>
                <div className="text-sm text-slate-600 dark:text-slate-400">
                  {fmtNum(m.layoff_total)} affected · {fmtNum(m.notice_count)} notices
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {(isAdmin || (members.data && members.data.length > 0)) && (
        <section>
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h2 className="text-lg font-semibold">
              Merged records ({members.data?.length ?? 0})
            </h2>
            {isAdmin && (
              <Link
                to="/admin/companies"
                search={{ name: c.name }}
                className="text-sm text-sky-700 hover:underline dark:text-sky-400"
              >
                Merge more…
              </Link>
            )}
          </div>
          <p className="mb-2 text-xs text-slate-500 dark:text-slate-400">
            Filings under other names (duplicates, store numbers) counted as this company.
          </p>
          {members.data && members.data.length > 0 && (
            <div className="card divide-y divide-slate-100 p-0 dark:divide-slate-800">
              {members.data.map((m) => (
                <div
                  key={m.company_id}
                  className="flex items-baseline justify-between gap-4 px-4 py-3"
                >
                  <div className="text-sm">{m.name}</div>
                  <div className="flex items-baseline gap-3 text-sm text-slate-600 dark:text-slate-400">
                    <span>
                      {fmtNum(m.layoff_total)} affected · {fmtNum(m.notice_count)} notices
                    </span>
                    {isAdmin && (
                      <button
                        type="button"
                        disabled={unmerge.isPending}
                        onClick={() => {
                          if (window.confirm(`Unmerge "${m.name}" from ${c.name}?`)) {
                            unmerge.mutate(m.company_id);
                          }
                        }}
                        className="text-xs font-medium text-red-600 hover:underline disabled:opacity-50 dark:text-red-400"
                      >
                        Unmerge
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      <section>
        <h2 className="mb-2 text-lg font-semibold">Notices ({notices.data?.total ?? 0})</h2>
        <div className="card divide-y divide-slate-100 p-0 dark:divide-slate-800">
          {notices.data?.items.map((n) => (
            <Link
              key={n.notice_id}
              to="/notices/$noticeId"
              params={{ noticeId: n.notice_id }}
              className="block px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <div className="flex items-baseline justify-between gap-4">
                <div className="text-sm font-medium">
                  {fmtDate(n.notice_date)} · {n.state}
                </div>
                <div className="text-sm text-slate-600 dark:text-slate-400">
                  {fmtNum(n.layoff_count)} affected
                </div>
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {n.location?.city || n.location?.county || "Location unspecified"}
              </div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

function Item({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </dt>
      <dd className="mt-0.5 text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}
