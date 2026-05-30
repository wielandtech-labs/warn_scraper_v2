import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { api } from "../api/client";
import { fmtDate, fmtNum } from "../lib/format";

export function NoticeDetail() {
  const { noticeId } = useParams({ from: "/notices/$noticeId" });
  const query = useQuery({
    queryKey: ["notice", noticeId],
    queryFn: () => api.getNotice(noticeId),
  });

  if (query.isLoading) {
    return <div className="card text-sm text-slate-500">Loading…</div>;
  }
  if (query.isError || !query.data) {
    return (
      <div className="card text-sm text-red-600">
        Notice not found.{" "}
        <Link to="/notices" className="font-medium underline">
          ← Back to all notices
        </Link>
      </div>
    );
  }

  const n = query.data;

  return (
    <div className="space-y-4">
      <div>
        <Link to="/notices" className="text-sm text-sky-700 hover:underline">
          ← All notices
        </Link>
      </div>
      <div className="card">
        <h1 className="text-2xl font-semibold">{n.employer}</h1>
        <div className="mt-1 text-sm text-slate-500">
          {n.state} · {fmtDate(n.notice_date)}
        </div>

        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <DescriptionItem label="Workers affected" value={fmtNum(n.layoff_count)} />
          <DescriptionItem label="Effective date" value={fmtDate(n.effective_date)} />
          <DescriptionItem label="Closure type" value={n.closure_type ?? "—"} />
          <DescriptionItem label="Address" value={n.address ?? "—"} />
          <DescriptionItem label="Scraped" value={fmtDate(n.scraped_at)} />
          {n.source_url && (
            <DescriptionItem
              label="Source"
              value={
                <a
                  className="text-sky-700 hover:underline"
                  href={n.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  state filing →
                </a>
              }
            />
          )}
          {n.raw_notice_url && (
            <DescriptionItem
              label="Original notice"
              value={
                <a
                  className="text-sky-700 hover:underline"
                  href={n.raw_notice_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  view document →
                </a>
              }
            />
          )}
        </dl>
      </div>

      {n.pdf_path && (
        <div className="card">
          <h2 className="mb-2 text-lg font-semibold">Notice Document</h2>
          <a
            className="text-sky-700 hover:underline text-sm"
            href={`/api/notices/${encodeURIComponent(n.notice_id)}/pdf`}
            target="_blank"
            rel="noreferrer"
          >
            Open PDF →
          </a>
          <iframe
            className="mt-3 w-full rounded border"
            style={{ height: "60vh" }}
            src={`/api/notices/${encodeURIComponent(n.notice_id)}/pdf`}
            title="Notice PDF"
          />
        </div>
      )}

      {n.company && (
        <div className="card">
          <h2 className="mb-2 text-lg font-semibold">Company</h2>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <DescriptionItem
              label="Name"
              value={
                <Link
                  to="/companies/$companyId"
                  params={{ companyId: String(n.company.id) }}
                  className="text-sky-700 hover:underline"
                >
                  {n.company.name}
                </Link>
              }
            />
            <DescriptionItem
              label="Website"
              value={
                n.company.website ? (
                  <a
                    className="text-sky-700 hover:underline"
                    href={n.company.website}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {n.company.website}
                  </a>
                ) : (
                  "—"
                )
              }
            />
            <DescriptionItem
              label="SIC"
              value={
                n.company.sic_code
                  ? `${n.company.sic_code}${n.company.sic_desc ? ` — ${n.company.sic_desc}` : ""}`
                  : "—"
              }
            />
            <DescriptionItem label="DUNS" value={n.company.duns ?? "—"} />
            <DescriptionItem
              label="Enrichment confidence"
              value={
                n.company.enrichment_confidence != null
                  ? Number(n.company.enrichment_confidence).toFixed(2)
                  : "—"
              }
            />
          </dl>
        </div>
      )}

      {n.location && (
        <div className="card">
          <h2 className="mb-2 text-lg font-semibold">Location</h2>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <DescriptionItem label="City" value={n.location.city ?? "—"} />
            <DescriptionItem label="County" value={n.location.county ?? "—"} />
            <DescriptionItem label="State" value={n.location.state} />
            <DescriptionItem label="ZIP" value={n.location.zip ?? "—"} />
            <DescriptionItem
              label="Coordinates"
              value={
                n.location.lat != null && n.location.lon != null
                  ? `${Number(n.location.lat).toFixed(4)}, ${Number(n.location.lon).toFixed(4)}`
                  : "—"
              }
            />
          </dl>
        </div>
      )}
    </div>
  );
}

function DescriptionItem({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="mt-0.5 text-slate-900">{value}</dd>
    </div>
  );
}
