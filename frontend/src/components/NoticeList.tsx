import { Link } from "@tanstack/react-router";

import type { NoticeOut } from "../api/types";
import { daysAgoIso, fmtDate, fmtNum } from "../lib/format";
import { ClosureBadge } from "./ClosureBadge";
import { CompanyLogo } from "./CompanyLogo";
import { StateSilhouette } from "./StateSilhouette";

// Notices filed this recently get a "new" marker.
export const NEW_NOTICE_DAYS = 7;

/* A compact notice list for the detail pages. `lead` picks what identifies a
   row: the employer (a state's recent filings) or the place (one company's
   filings, where the employer is the same on every row). Workers affected
   get an inline bar on one scale -- the largest notice in the list. */
export function NoticeList({
  notices,
  lead,
}: {
  notices: NoticeOut[];
  lead: "employer" | "place";
}) {
  const max = Math.max(1, ...notices.map((n) => n.layoff_count ?? 0));
  const newCutoff = daysAgoIso(NEW_NOTICE_DAYS);
  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {notices.map((n) => {
        const place = [n.location?.city, n.location?.county].filter(Boolean).join(", ");
        const isNew = (n.notice_date ?? "") >= newCutoff;
        return (
          <li key={n.notice_id}>
            <Link
              to="/notices/$noticeId"
              params={{ noticeId: n.notice_id }}
              className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              {lead === "employer" ? (
                <CompanyLogo
                  name={n.company?.name ?? n.employer}
                  companyId={n.company?.id}
                  hasLogo={!!n.company?.has_logo}
                  size={28}
                />
              ) : (
                <StateSilhouette
                  code={n.state}
                  size={28}
                  className="shrink-0 text-slate-300 dark:text-slate-600"
                />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  {isNew && (
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand" title="Filed in the last week" />
                  )}
                  <span className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                    {lead === "employer" ? n.employer : place || "Location unspecified"}
                  </span>
                  <ClosureBadge category={n.closure_category} />
                </div>
                <div className="truncate text-xs text-slate-500 dark:text-slate-400">
                  {lead === "employer"
                    ? `${fmtDate(n.notice_date)} · ${place || "Location unspecified"}`
                    : `${fmtDate(n.notice_date)} · ${n.state}`}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {n.layoff_count != null && (
                  <span
                    aria-hidden
                    className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-slate-100 sm:block dark:bg-slate-800"
                  >
                    <span
                      className="block h-full rounded-full bg-brand/70"
                      style={{ width: `${Math.max(4, (n.layoff_count / max) * 100)}%` }}
                    />
                  </span>
                )}
                <span className="w-14 text-right text-sm font-semibold tabular-nums">
                  {fmtNum(n.layoff_count)}
                </span>
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
