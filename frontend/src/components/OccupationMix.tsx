import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { fmtNum } from "../lib/format";

/** Occupation mix for a notice. Actual position titles + counts when the
 *  employer's WARN filing listed them (source "employer_filing"); otherwise
 *  the national OEWS staffing pattern of the company's NAICS industry.
 *  Renders nothing when neither is available. Plain CSS bars — no recharts,
 *  so notice-detail stays out of the chart chunk. */
export function OccupationMix({ noticeId }: { noticeId: string }) {
  const query = useQuery({
    queryKey: ["occupation-mix", noticeId],
    queryFn: () => api.getOccupationMix(noticeId),
  });

  const mix = query.data;
  if (!mix || !mix.available || mix.occupations.length === 0) return null;

  const filed = mix.source === "employer_filing";
  const maxPct = mix.occupations[0].pct;
  const matchNote =
    mix.match_level === "sector"
      ? "sector-level NAICS match"
      : `${mix.match_level} NAICS match`;

  return (
    <div className="card">
      <h2 className="mb-2 text-lg font-semibold">
        {filed ? "Positions affected" : "Estimated occupation mix"}
      </h2>
      <ul className="space-y-1.5">
        {mix.occupations.map((o) => (
          <li key={o.soc_code ?? o.title} className="flex items-center gap-2 text-sm">
            <span className="w-56 shrink-0 truncate sm:w-72" title={o.title}>
              {o.title}
            </span>
            <span className="h-3 flex-1 rounded-sm bg-slate-100 dark:bg-slate-800">
              <span
                className="block h-3 rounded-sm bg-sky-600 dark:bg-sky-500"
                style={{ width: `${Math.max(2, (o.pct / maxPct) * 100)}%` }}
              />
            </span>
            <span className="w-24 shrink-0 text-right text-slate-600 dark:text-slate-400">
              {o.estimate != null && o.estimate >= 1
                ? `${filed ? "" : "~"}${fmtNum(o.estimate)} workers`
                : `${o.pct}%`}
            </span>
          </li>
        ))}
      </ul>
      {filed ? (
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          Job titles and worker counts as reported in the employer's WARN
          filing — the actual affected positions, not an estimate.
        </p>
      ) : (
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          Top {mix.occupations.length} occupations covering{" "}
          {mix.coverage_pct != null ? `${mix.coverage_pct}%` : "part"} of{" "}
          {mix.industry_title} employment ({matchNote}, OEWS {mix.oews_vintage}).
          Estimates apply the national staffing pattern for this industry to the
          reported worker count — a statistical prior from the industry's
          employment mix, not information about the actual affected roles.
        </p>
      )}
    </div>
  );
}
