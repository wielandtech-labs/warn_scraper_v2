import { useState, type ReactNode } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { api } from "../api/client";
import { CompanyLogo } from "../components/CompanyLogo";
import { Figure, Figures } from "../components/Figures";
import { NoticeList } from "../components/NoticeList";
import { PageHeader } from "../components/PageHeader";
import { QueryError } from "../components/QueryError";
import { RepeatRisk } from "../components/RepeatRisk";
import { SkeletonBlock, SkeletonRows } from "../components/Skeleton";
import { StateSilhouette } from "../components/StateSilhouette";
import { YearBars } from "../components/YearBars";
import { useAuth } from "../hooks/useAuth";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum, fmtRelativeDays, SOURCE_LABEL, stateName } from "../lib/format";

const NOTICE_PAGE = 25;
// Merged-record names shown before "Show all".
const MEMBERS_PREVIEW = 5;

export function CompanyDetail() {
  const { companyId } = useParams({ from: "/companies/$companyId" });
  const id = Number(companyId);

  const company = useQuery({
    queryKey: ["company", id],
    queryFn: () => api.getCompany(id),
    enabled: !Number.isNaN(id),
  });

  const summary = useQuery({
    queryKey: ["company", id, "summary"],
    queryFn: () => api.getCompanySummary(id),
    enabled: !Number.isNaN(id),
  });

  // "Show more" fetches only the next page, not the whole list again.
  const notices = useInfiniteQuery({
    queryKey: ["company", id, "notices", "pages"],
    queryFn: ({ pageParam }) =>
      api.listCompanyNotices(id, { limit: NOTICE_PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined,
    enabled: !Number.isNaN(id),
  });
  const noticeItems = notices.data?.pages.flatMap((p) => p.items) ?? [];
  const noticeTotal = notices.data?.pages[0]?.total ?? 0;
  const [showAllMembers, setShowAllMembers] = useState(false);

  const family = useQuery({
    queryKey: ["company", id, "family"],
    queryFn: () => api.getCompanyFamily(id),
    enabled: !Number.isNaN(id),
  });

  // 404s while the feature is dark — no retries, and the card just stays hidden.
  const repeatRisk = useQuery({
    queryKey: ["company", id, "repeat-risk"],
    queryFn: () => api.getCompanyRepeatRisk(id),
    enabled: !Number.isNaN(id),
    retry: false,
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
    company.data ? `${company.data.name} — WARN Index` : undefined,
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
  const s = summary.data;
  const sinceYear = s?.first_notice?.slice(0, 4);
  const stateMax = Math.max(1, ...(s?.by_state ?? []).map((r) => r.layoff_total));
  const familyMax = Math.max(1, ...(family.data ?? []).map((m) => m.layoff_total));
  const shownMembers = showAllMembers ? members.data : members.data?.slice(0, MEMBERS_PREVIEW);

  return (
    <div className="space-y-6">
      {/* The detail URL carries the list's search params (see router.tsx);
          re-applying them restores the exact filters/sort/page. */}
      <Link to="/companies" search={(prev) => prev} className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
        ← All companies
      </Link>

      <PageHeader
        kicker={c.sic_desc ?? "Company"}
        title={
          <span className="flex items-center gap-4">
            <CompanyLogo name={c.name} companyId={c.id} hasWebsite={!!c.website} size={56} />
            <span className="min-w-0">{c.name}</span>
          </span>
        }
        lede={
          s && s.notice_count > 0 ? (
            <>
              <span className="font-semibold text-slate-900 dark:text-slate-100">
                {fmtNum(s.layoff_total)}
              </span>{" "}
              workers affected across {fmtNum(s.notice_count)} WARN{" "}
              {s.notice_count === 1 ? "notice" : "notices"} in {s.by_state.length}{" "}
              {s.by_state.length === 1 ? "state" : "states"}
              {sinceYear ? ` since ${sinceYear}` : ""}.
            </>
          ) : undefined
        }
        aside={
          c.website ? (
            <a
              href={c.website}
              target="_blank"
              rel="noreferrer"
              className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
            >
              {c.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} ↗
            </a>
          ) : undefined
        }
      />

      {c.canonical_company_id != null && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
          This record is counted under{" "}
          <Link
            to="/companies/$companyId"
            params={{ companyId: String(c.canonical_company_id) }}
            search={(prev) => prev}
            className="font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            its main company record
          </Link>
          .
        </p>
      )}

      <Figures>
        <Figure label="Workers affected" value={s ? fmtNum(s.layoff_total) : null} accent />
        <Figure label="Notices" value={s ? fmtNum(s.notice_count) : null} />
        <Figure label="States" value={s ? fmtNum(s.by_state.length) : null} />
        <Figure
          label="Latest notice"
          value={s ? fmtDate(s.last_notice) : null}
          note={fmtRelativeDays(s?.last_notice) ?? undefined}
        />
      </Figures>

      {repeatRisk.data && <RepeatRisk risk={repeatRisk.data} />}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {s && s.by_year.length > 1 && (
            <section className="card">
              <h2 className="text-lg font-semibold">Workers affected by year</h2>
              <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
                By notice date, across every filing rolled up to this company.
              </p>
              <YearBars rows={s.by_year} />
            </section>
          )}

          <section className="card p-0">
            <h2 className="px-5 pb-1 pt-5 text-lg font-semibold">
              Filings{" "}
              <span className="font-sans text-sm font-normal text-slate-500 dark:text-slate-400">
                {notices.data ? fmtNum(noticeTotal) : ""}
              </span>
            </h2>
            {notices.isLoading && <SkeletonRows rows={6} />}
            {notices.isError && (
              <QueryError message="Error loading notices." onRetry={() => notices.refetch()} />
            )}
            {notices.data && <NoticeList notices={noticeItems} lead="place" />}
            {notices.hasNextPage && (
              <div className="border-t border-slate-100 px-5 py-3 dark:border-slate-800">
                <button
                  type="button"
                  disabled={notices.isFetchingNextPage}
                  onClick={() => notices.fetchNextPage()}
                  className="text-sm font-medium text-sky-700 hover:underline disabled:opacity-50 dark:text-sky-400"
                >
                  {notices.isFetchingNextPage
                    ? "Loading…"
                    : `Show more (${fmtNum(noticeTotal - noticeItems.length)} left)`}
                </button>
              </div>
            )}
          </section>
        </div>

        <aside className="space-y-6">
          {s && s.by_state.length > 0 && (
            <section className="card">
              <h2 className="mb-2 text-lg font-semibold">Where</h2>
              <ul className="space-y-2">
                {s.by_state.slice(0, 10).map((r) => (
                  <li key={r.state}>
                    <Link
                      to="/states/$state"
                      params={{ state: r.state }}
                      className="group flex items-center gap-2.5"
                    >
                      <StateSilhouette
                        code={r.state}
                        size={24}
                        className="shrink-0 text-slate-300 transition-colors group-hover:text-brand dark:text-slate-600"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2 text-sm">
                          <span className="truncate font-medium group-hover:underline">{stateName(r.state)}</span>
                          <span className="tabular-nums text-slate-600 dark:text-slate-400">
                            {fmtNum(r.layoff_total)}
                          </span>
                        </div>
                        <div aria-hidden className="mt-1 h-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                          <div
                            className="h-full rounded-full bg-brand/70"
                            style={{ width: `${(r.layoff_total / stateMax) * 100}%` }}
                          />
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
              {s.by_state.length > 10 && (
                <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                  + {s.by_state.length - 10} more states
                </p>
              )}
            </section>
          )}

          <section className="card">
            <h2 className="mb-3 text-lg font-semibold">Profile</h2>
            <dl className="space-y-3 text-sm">
              <Item label="Industry (SIC)" value={c.sic_code ? `${c.sic_code} · ${c.sic_desc ?? ""}` : "—"} />
              {/* provider fields are present in the payload only for paid/admin
                  sessions — render whatever the API returned, no role logic here. */}
              {c.unique_id != null && <Item label="ID" value={c.unique_id} />}
              {c.employee_count != null && (
                <Item label="Employees" value={fmtNum(c.employee_count)} />
              )}
              {c.parent_company_name != null && (
                <Item
                  label="Parent"
                  value={
                    c.parent_unique_id != null
                      ? `${c.parent_company_name} · ID ${c.parent_unique_id}`
                      : c.parent_company_name
                  }
                />
              )}
              {c.parent_company_name == null && c.parent_unique_id != null && (
                <Item label="Parent ID" value={c.parent_unique_id} />
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
          </section>

          {family.data && family.data.length >= 2 && (
            <section className="card">
              <h2 className="text-lg font-semibold">Corporate family</h2>
              <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
                {family.data.length} companies in the same corporate family, with
                layoffs rolled up across each one.
              </p>
              <ul className="space-y-2.5">
                {family.data.map((m) => (
                  <li key={m.company_id}>
                    <Link
                      to="/companies/$companyId"
                      params={{ companyId: String(m.company_id) }}
                      search={(prev) => prev}
                      className="group flex items-center gap-2.5"
                    >
                      <CompanyLogo name={m.name} companyId={m.company_id} size={24} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2 text-sm">
                          <span className="truncate font-medium group-hover:underline">
                            {m.name}
                            {m.is_self && (
                              <span className="ml-1.5 text-xs font-normal text-slate-500 dark:text-slate-400">
                                (this)
                              </span>
                            )}
                          </span>
                          <span className="tabular-nums text-slate-600 dark:text-slate-400">
                            {fmtNum(m.layoff_total)}
                          </span>
                        </div>
                        <div aria-hidden className="mt-1 h-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                          <div
                            className={`h-full rounded-full ${m.is_self ? "bg-brand" : "bg-slate-400 dark:bg-slate-500"}`}
                            style={{ width: `${(m.layoff_total / familyMax) * 100}%` }}
                          />
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(isAdmin || (members.data && members.data.length > 0)) && (
            <section className="card">
              <div className="flex items-baseline justify-between gap-4">
                <h2 className="text-lg font-semibold">
                  Also filed as{" "}
                  <span className="font-sans text-sm font-normal text-slate-500 dark:text-slate-400">
                    {members.data?.length ?? 0}
                  </span>
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
              {shownMembers && shownMembers.length > 0 && (
                <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
                  {shownMembers.map((m) => (
                    <li key={m.company_id} className="flex items-baseline justify-between gap-3 py-2">
                      <span className="min-w-0 truncate">{m.name}</span>
                      <span className="flex shrink-0 items-baseline gap-3 text-slate-600 dark:text-slate-400">
                        <span className="tabular-nums">{fmtNum(m.layoff_total)}</span>
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
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {members.data && members.data.length > MEMBERS_PREVIEW && (
                <button
                  type="button"
                  aria-expanded={showAllMembers}
                  onClick={() => setShowAllMembers((v) => !v)}
                  className="mt-2 text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
                >
                  {showAllMembers ? "Show fewer" : `Show all ${members.data.length}`}
                </button>
              )}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}

function Item({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
        {label}
      </dt>
      <dd className="mt-0.5 text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}
