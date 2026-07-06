import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { ApiError, api } from "../api/client";
import type { IndustryScorecard } from "../api/types";
import { QueryError } from "../components/QueryError";
import { ReportMarkdown } from "../components/ReportMarkdown";
import { SkeletonBlock, SkeletonRows } from "../components/Skeleton";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum } from "../lib/format";

// Mirrors GRADE_LABEL in warn_v2/reports/industry.py.
const GRADE_STYLE: Record<string, { badge: string; label: string }> = {
  A: { badge: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300", label: "easing sharply" },
  B: { badge: "bg-lime-100 text-lime-800 dark:bg-lime-950 dark:text-lime-300", label: "easing" },
  C: { badge: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300", label: "stable" },
  D: { badge: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300", label: "elevated" },
  F: { badge: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300", label: "surging" },
};

export function GradeBadge({ grade }: { grade: string }) {
  const style = GRADE_STYLE[grade];
  if (!style) {
    return (
      <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
        N/A
      </span>
    );
  }
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${style.badge}`}
      title={`Layoff pressure ${style.label}`}
    >
      {grade} · {style.label}
    </span>
  );
}

function deltaCell(card: IndustryScorecard): string {
  if (card.delta_pct === null) {
    return card.cur_layoffs > 0 && card.prior_layoffs === 0 ? "new" : "—";
  }
  return `${card.delta_pct > 0 ? "+" : ""}${Math.round(card.delta_pct)}%`;
}

function ScorecardGrid({ cards }: { cards: IndustryScorecard[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {cards.map((card) => (
        <Link
          key={card.sector}
          to="/reports/industry/$sector"
          params={{ sector: card.sector }}
          className="card space-y-2 hover:border-sky-300 hover:bg-sky-50 dark:hover:border-sky-800 dark:hover:bg-sky-950"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="font-medium leading-snug text-slate-900 dark:text-slate-100">
              {card.sector_name}
            </div>
            <GradeBadge grade={card.grade} />
          </div>
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-slate-500 dark:text-slate-400">
              {card.score !== null ? (
                <>
                  Score <span className="font-semibold text-slate-900 dark:text-slate-100">{card.score}</span>
                  /100
                </>
              ) : (
                "Not enough data"
              )}
            </span>
            <span className="text-right">
              <span className="font-semibold tabular-nums">{fmtNum(card.cur_layoffs)}</span>{" "}
              <span className="text-xs text-slate-500 dark:text-slate-400">
                workers · {deltaCell(card)} vs prior 90d
              </span>
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}

export function ReportsPage() {
  useDocumentTitle("Economic sentiment — WARN Tracker");

  // [] until the first weekly report job populates the volume.
  const scorecards = useQuery({
    queryKey: ["reports", "industries"],
    queryFn: api.listIndustryScorecards,
  });
  // A 404 just means the national report hasn't been generated yet.
  const national = useQuery({
    queryKey: ["report", "US"],
    queryFn: () => api.getReport("US"),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  });
  const nationalMissing =
    national.isError && national.error instanceof ApiError && national.error.status === 404;

  const generatedAt = scorecards.data?.[0]?.generated_at;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Economic sentiment</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Weekly layoff-trend scorecards by industry and a national outlook, computed
          from WARN notices (trailing 90 days vs the prior 90). Scores are 0–100,
          higher is healthier; industry figures cover only notices matched to a NAICS
          code, so treat them as directional.
          {generatedAt && <> Updated {fmtDate(generatedAt)}.</>}
        </p>
      </div>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Industry scorecards</h2>
        {scorecards.isLoading ? (
          <SkeletonRows rows={4} />
        ) : scorecards.isError ? (
          <QueryError
            message="Error loading industry scorecards."
            onRetry={() => scorecards.refetch()}
          />
        ) : scorecards.data && scorecards.data.length > 0 ? (
          <ScorecardGrid cards={scorecards.data} />
        ) : (
          <div className="card text-sm text-slate-500 dark:text-slate-400">
            No scorecards yet — they are generated by a weekly job and will appear
            after its first run.
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">National outlook</h2>
        <div className="card">
          {national.isLoading ? (
            <div className="space-y-2">
              <SkeletonBlock className="h-4 w-1/3" />
              <SkeletonBlock className="h-24 w-full" />
              <SkeletonBlock className="h-4 w-2/3" />
            </div>
          ) : nationalMissing ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              No national report yet — it is generated by a weekly job and will
              appear after its first run.
            </p>
          ) : national.isError ? (
            <QueryError
              message="Error loading the national report."
              onRetry={() => national.refetch()}
            />
          ) : national.data ? (
            <ReportMarkdown markdown={national.data} skipH1 />
          ) : null}
        </div>
      </section>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        Looking for a specific state? Each{" "}
        <Link to="/states" className="font-medium text-sky-700 hover:underline dark:text-sky-400">
          state page
        </Link>{" "}
        carries its own economic outlook section.
      </p>
    </div>
  );
}
