import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { api, ApiError } from "../api/client";
import { ClosureBadge } from "../components/ClosureBadge";
import { CompanyLogo } from "../components/CompanyLogo";
import { EmbedButton } from "../components/EmbedDialog";
import { Figure, Figures } from "../components/Figures";
import { LocationMap } from "../components/LocationMap";
import { NoticeList } from "../components/NoticeList";
import { OccupationMix } from "../components/OccupationMix";
import { PageHeader } from "../components/PageHeader";
import { QueryError } from "../components/QueryError";
import { SkeletonBlock, SkeletonRows } from "../components/Skeleton";
import { StateSilhouette } from "../components/StateSilhouette";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum, fmtRelativeDays, stateName } from "../lib/format";

const OTHER_FILINGS = 5;

export function NoticeDetail() {
  const { noticeId } = useParams({ from: "/notices/$noticeId" });
  const query = useQuery({
    queryKey: ["notice", noticeId],
    queryFn: () => api.getNotice(noticeId),
  });

  // The company's other filings, for the "Other filings" list. One extra row
  // so the list still fills when this notice is among the latest. A merged
  // duplicate's own list holds only its rows, so ask its canonical record.
  const company = query.data?.company;
  const companyId = company ? (company.canonical_company_id ?? company.id) : undefined;
  const companyNotices = useQuery({
    queryKey: ["company", companyId, "notices", OTHER_FILINGS + 1],
    queryFn: () => api.listCompanyNotices(companyId!, { limit: OTHER_FILINGS + 1 }),
    enabled: companyId != null,
  });
  const [showPdf, setShowPdf] = useState(false);

  useDocumentTitle(
    query.data
      ? `${query.data.employer} (${query.data.state}) Layoffs & WARN Notice — WARN Index`
      : undefined,
  );

  if (query.isLoading) {
    return (
      <div className="card space-y-3">
        <SkeletonBlock className="h-7 w-2/3" />
        <SkeletonBlock className="h-4 w-1/3" />
        <SkeletonBlock className="h-24 w-full" />
      </div>
    );
  }
  // A 404 is a bad link — offer the way back. Anything else is transient, so
  // offer a retry instead.
  if (query.isError && !(query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <QueryError message="Error loading this notice." onRetry={() => query.refetch()} />
    );
  }
  if (query.isError || !query.data) {
    return (
      <div className="card text-sm text-red-600 dark:text-red-400">
        Notice not found.{" "}
        <Link to="/notices" search={(prev) => prev} className="font-medium underline">
          ← Back to all notices
        </Link>
      </div>
    );
  }

  const n = query.data;
  const loc = n.location;
  const place = [loc?.city, loc?.county].filter(Boolean).join(", ");
  const fetched = companyNotices.data?.items ?? [];
  const others = fetched.filter((o) => o.notice_id !== n.notice_id).slice(0, OTHER_FILINGS);
  // This notice is in the company's list unless it is superseded (fetchable
  // by id, excluded from lists). When the whole list came back and it isn't
  // there, every row is "other".
  const total = companyNotices.data?.total ?? 0;
  const listed =
    fetched.some((o) => o.notice_id === n.notice_id) || fetched.length < total;
  const otherTotal = Math.max(0, total - (listed ? 1 : 0));
  const pdfUrl = `/api/notices/${encodeURIComponent(n.notice_id)}/pdf`;

  return (
    <div className="space-y-6">
      {/* The detail URL carries the list's search params (see router.tsx);
          re-applying them restores the exact filters/sort/page. */}
      <Link to="/notices" search={(prev) => prev} className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
        ← All notices
      </Link>

      <PageHeader
        kicker={
          <>
            WARN notice ·{" "}
            <Link to="/states/$state" params={{ state: n.state }} className="hover:underline">
              {stateName(n.state)}
            </Link>
          </>
        }
        title={
          <span className="flex items-center gap-4">
            <CompanyLogo
              name={n.company?.name ?? n.employer}
              companyId={n.company?.id}
              hasLogo={!!n.company?.has_logo}
              size={56}
            />
            <span className="min-w-0">{n.employer}</span>
          </span>
        }
        lede={
          <>
            {n.closure_category === "Closure" ? "Closure" : "Layoff"} notice filed{" "}
            {fmtDate(n.notice_date)}
            {place ? ` in ${place}` : ""}.{" "}
            <ClosureBadge category={n.closure_category} />
          </>
        }
        aside={
          <div className="flex flex-wrap gap-2">
            {n.raw_notice_url && (
              <a className="btn-secondary" href={n.raw_notice_url} target="_blank" rel="noreferrer">
                Original notice ↗
              </a>
            )}
            {n.source_url && (
              <a className="btn-secondary" href={n.source_url} target="_blank" rel="noreferrer">
                State listing ↗
              </a>
            )}
            <EmbedButton noticeId={n.notice_id} employer={n.company?.name ?? n.employer} />
          </div>
        }
      />

      <Figures>
        <Figure label="Workers affected" value={fmtNum(n.layoff_count)} accent />
        <Figure label="Filed" value={fmtDate(n.notice_date)} note={fmtRelativeDays(n.notice_date) ?? undefined} />
        <Figure
          label="Effective"
          value={fmtDate(n.effective_date)}
          note={fmtRelativeDays(n.effective_date) ?? undefined}
        />
        <Figure label="Type" value={n.closure_type ?? n.closure_category ?? "—"} />
      </Figures>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          {/* Only fetch the mix when a NAICS code exists (~16% of notices);
              the component also renders nothing when OEWS has no pattern. */}
          {n.company?.naics_code && <OccupationMix noticeId={n.notice_id} />}

          {n.pdf_path && (
            <section className="card">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-lg font-semibold">Notice document</h2>
                <a
                  className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
                  href={pdfUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open PDF ↗
                </a>
              </div>
              {/* The PDF can run to megabytes; load it only on request. */}
              {showPdf ? (
                <iframe
                  className="mt-3 w-full rounded border dark:border-slate-800"
                  style={{ height: "70vh" }}
                  src={pdfUrl}
                  title="Notice PDF"
                />
              ) : (
                <button
                  type="button"
                  onClick={() => setShowPdf(true)}
                  className="mt-3 flex h-40 w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 text-sm text-slate-600 transition-colors hover:border-slate-400 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800/50"
                >
                  <svg aria-hidden viewBox="0 0 24 24" className="h-8 w-8 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
                    <path d="M14 3v5h5M9 13h6M9 17h6" />
                  </svg>
                  Preview the filed notice
                </button>
              )}
            </section>
          )}

          {n.company && (
            <section className="card p-0">
              <div className="flex items-center justify-between gap-3 px-5 pb-1 pt-5">
                <h2 className="text-lg font-semibold">
                  Other filings by {n.company.name}
                </h2>
                {otherTotal > 0 && companyId != null && (
                  <Link
                    to="/companies/$companyId"
                    params={{ companyId: String(companyId) }}
                    className="shrink-0 text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
                  >
                    All {fmtNum(total)} →
                  </Link>
                )}
              </div>
              {companyNotices.isLoading && <SkeletonRows rows={3} />}
              {companyNotices.data && others.length === 0 && (
                <p className="px-5 pb-5 pt-2 text-sm text-slate-500 dark:text-slate-400">
                  This is the only WARN notice on record for this company.
                </p>
              )}
              {others.length > 0 && <NoticeList notices={others} lead="place" />}
            </section>
          )}
        </div>

        <aside className="space-y-6">
          {loc && (
            <section className="card">
              <h2 className="mb-3 text-lg font-semibold">Location</h2>
              {loc.lat != null && loc.lon != null ? (
                <LocationMap
                  lat={Number(loc.lat)}
                  lon={Number(loc.lon)}
                  label={place || stateName(loc.state)}
                />
              ) : (
                <div className="flex justify-center py-2">
                  <StateSilhouette code={loc.state} size={120} className="text-slate-200 dark:text-slate-700" />
                </div>
              )}
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                <Item label="City" value={loc.city ?? "—"} />
                <Item label="County" value={loc.county ?? "—"} />
                <Item label="State" value={stateName(loc.state)} />
                <Item label="ZIP" value={loc.zip ?? "—"} />
              </dl>
              {n.address && (
                <dl className="mt-3 text-sm">
                  <Item label="Address as filed" value={n.address} />
                </dl>
              )}
            </section>
          )}

          {n.company && (
            <section className="card">
              <h2 className="mb-3 text-lg font-semibold">Company</h2>
              <Link
                to="/companies/$companyId"
                params={{ companyId: String(n.company.id) }}
                className="group flex items-center gap-3"
              >
                <CompanyLogo
                  name={n.company.name}
                  companyId={n.company.id}
                  hasLogo={!!n.company.has_logo}
                  size={36}
                />
                <span className="font-medium text-slate-900 group-hover:underline dark:text-slate-100">
                  {n.company.name}
                </span>
              </Link>
              <dl className="mt-3 space-y-3 text-sm">
                {n.company.website && (
                  <Item
                    label="Website"
                    value={
                      <a
                        className="text-sky-700 hover:underline dark:text-sky-400"
                        href={n.company.website}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {n.company.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}
                      </a>
                    }
                  />
                )}
                <Item
                  label="Industry (SIC)"
                  value={
                    n.company.sic_code
                      ? `${n.company.sic_code} — ${n.company.sic_desc ?? ""}`
                      : "—"
                  }
                />
              </dl>
            </section>
          )}

          <p className="text-xs text-slate-500 dark:text-slate-400">
            Collected {fmtDate(n.scraped_at)} from the {stateName(n.state)} WARN listing.
          </p>
        </aside>
      </div>
    </div>
  );
}

function Item({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div>
      <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
        {label}
      </dt>
      <dd className="mt-0.5 break-words text-slate-900 dark:text-slate-100">{value}</dd>
    </div>
  );
}
