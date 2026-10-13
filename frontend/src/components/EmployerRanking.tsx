import { Link } from "@tanstack/react-router";

import type { EmployerStat } from "../api/types";
import { useTheme } from "../hooks/useTheme";
import { fmtNum } from "../lib/format";
import { CHART_COLORS } from "../lib/themeColors";
import { CompanyLogo } from "./CompanyLogo";
import { Peek } from "./Peek";
import { CompanyPeek } from "./peeks";

/* Employers ranked by workers affected: rank, logo, name (with a hover
   peek), and a bar on one shared scale -- the largest employer's total. */
export function EmployerRanking({ rows }: { rows: EmployerStat[] }) {
  const { resolved } = useTheme();
  const color = CHART_COLORS[resolved].layoffs;
  const max = Math.max(1, ...rows.map((e) => e.layoff_total));
  return (
    <ol className="divide-y divide-slate-100 dark:divide-slate-800">
      {rows.map((e, i) => (
        <li key={e.employer} className="flex items-center gap-3 py-2.5">
          <span className="w-6 shrink-0 text-right font-display text-sm text-slate-400 tabular-nums">
            {i + 1}
          </span>
          <CompanyLogo name={e.employer} companyId={e.company_id} size={28} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">
              {e.company_id ? (
                <Peek content={() => <CompanyPeek id={e.company_id!} name={e.employer} />}>
                  <Link
                    to="/companies/$companyId"
                    params={{ companyId: String(e.company_id) }}
                    className="text-slate-900 hover:text-sky-700 hover:underline dark:text-slate-100 dark:hover:text-sky-400"
                  >
                    {e.employer}
                  </Link>
                </Peek>
              ) : (
                e.employer
              )}
            </div>
            <div aria-hidden className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded-full"
                style={{ width: `${(e.layoff_total / max) * 100}%`, backgroundColor: color }}
              />
            </div>
          </div>
          <div className="w-28 shrink-0 text-right">
            <div className="text-sm font-semibold tabular-nums">{fmtNum(e.layoff_total)}</div>
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {e.notice_count} {e.notice_count === 1 ? "notice" : "notices"}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
