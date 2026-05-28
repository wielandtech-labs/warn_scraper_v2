import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { api } from "../api/client";
import { fmtDate, fmtNum } from "../lib/format";

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

  if (Number.isNaN(id)) {
    return <div className="card text-red-600">Invalid company ID.</div>;
  }
  if (company.isLoading) {
    return <div className="card text-slate-500">Loading…</div>;
  }
  if (company.isError || !company.data) {
    return (
      <div className="card text-red-600">
        Company not found.{" "}
        <Link to="/companies" className="font-medium underline">
          ← Back
        </Link>
      </div>
    );
  }

  const c = company.data;

  return (
    <div className="space-y-4">
      <div>
        <Link to="/companies" className="text-sm text-sky-700 hover:underline">
          ← All companies
        </Link>
      </div>
      <div className="card">
        <h1 className="text-2xl font-semibold">{c.name}</h1>
        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          {c.website && (
            <Item
              label="Website"
              value={
                <a className="text-sky-700 hover:underline" href={c.website} target="_blank" rel="noreferrer">
                  {c.website}
                </a>
              }
            />
          )}
          <Item label="SIC" value={c.sic_code ? `${c.sic_code} · ${c.sic_desc ?? ""}` : "—"} />
          <Item label="DUNS" value={c.duns ?? "—"} />
          <Item
            label="Enriched"
            value={
              c.enriched_at
                ? `${fmtDate(c.enriched_at)} · confidence ${
                    c.enrichment_confidence != null
                      ? Number(c.enrichment_confidence).toFixed(2)
                      : "?"
                  }`
                : "Not yet enriched"
            }
          />
        </dl>
      </div>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Notices ({notices.data?.total ?? 0})</h2>
        <div className="card divide-y divide-slate-100 p-0">
          {notices.data?.items.map((n) => (
            <Link
              key={n.notice_id}
              to="/notices/$noticeId"
              params={{ noticeId: n.notice_id }}
              className="block px-4 py-3 hover:bg-slate-50"
            >
              <div className="flex items-baseline justify-between gap-4">
                <div className="text-sm font-medium">
                  {fmtDate(n.notice_date)} · {n.state}
                </div>
                <div className="text-sm text-slate-600">
                  {fmtNum(n.layoff_count)} affected
                </div>
              </div>
              <div className="text-xs text-slate-500">
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
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="mt-0.5 text-slate-900">{value}</dd>
    </div>
  );
}
