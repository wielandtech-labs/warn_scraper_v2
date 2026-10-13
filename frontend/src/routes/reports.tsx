import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { ApiError, api } from "../api/client";
import type { IndustryScorecard } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { QueryError } from "../components/QueryError";
import { ReportMarkdown } from "../components/ReportMarkdown";
import { SkeletonBlock, SkeletonRows } from "../components/Skeleton";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum } from "../lib/format";
import { deltaCell } from "../lib/scorecard";

// Mirrors GRADE_LABEL in warn_v2/reports/industry.py.
const GRADE_STYLE: Record<string, { badge: string; label: string }> = {
  A: { badge: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300", label: "easing sharply" },
  B: { badge: "bg-lime-100 text-lime-800 dark:bg-lime-950 dark:text-lime-300", label: "easing" },
  C: { badge: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300", label: "stable" },
  D: { badge: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300", label: "elevated" },
  F: { badge: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300", label: "surging" },
};

export function GradeTile({ grade }: { grade: string }) {
  const style = GRADE_STYLE[grade];
  return (
    <span
      className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl font-display text-2xl font-semibold ${
        style?.badge ?? "bg-slate-100 text-slate-400 dark:bg-slate-800"
      }`}
      title={style ? `Layoff pressure ${style.label}` : "Not enough data"}
    >
      {style ? grade : "–"}
    </span>
  );
}

function ScorecardGrid({ cards }: { cards: IndustryScorecard[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {cards.map((card) => {
        // A rise in layoffs is bad news: red up-arrow; a fall, a muted
        // down-arrow. "new" (from zero to some) is the steepest rise of all.
        const fromZero = card.delta_pct === null && card.cur_layoffs > 0 && card.prior_layoffs === 0;
        const rising = fromZero || (card.delta_pct !== null && card.delta_pct > 0);
        return (
          <Link
            key={card.sector}
            to="/reports/industry/$sector"
            params={{ sector: card.sector }}
            className="card group flex flex-col gap-3 transition-colors hover:border-slate-300 dark:hover:border-slate-700"
          >
            <div className="flex items-start gap-3">
              <GradeTile grade={card.grade} />
              <div className="min-w-0 flex-1">
                <div className="font-medium leading-snug text-slate-900 group-hover:underline dark:text-slate-100">
                  {card.sector_name}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {GRADE_STYLE[card.grade]?.label ?? "not enough data"} · NAICS {card.sector}
                </div>
              </div>
            </div>
            {/* Score meter: 0-100, higher is healthier. */}
            <div>
              <div className="flex items-baseline justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>Score</span>
                <span className="font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                  {card.score ?? "—"}
                  <span className="font-normal text-slate-500 dark:text-slate-400">/100</span>
                </span>
              </div>
              <div aria-hidden className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div
                  className="h-full rounded-full bg-slate-700 dark:bg-slate-300"
                  style={{ width: `${card.score ?? 0}%` }}
                />
              </div>
            </div>
            <div className="flex items-baseline justify-between text-sm">
              <span>
                <span className="font-semibold tabular-nums">{fmtNum(card.cur_layoffs)}</span>{" "}
                <span className="text-xs text-slate-500 dark:text-slate-400">workers, last 90 days</span>
              </span>
              <span
                className={`text-xs font-semibold tabular-nums ${
                  rising ? "text-brand dark:text-brand-dark" : "text-slate-500 dark:text-slate-400"
                }`}
                title="vs the prior 90 days"
              >
                {rising ? "▲ " : card.delta_pct !== null && card.delta_pct < 0 ? "▼ " : ""}
                {deltaCell(card)}
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function GradeSummary({ cards }: { cards: IndustryScorecard[] }) {
  const counts = ["A", "B", "C", "D", "F"].map((g) => ({
    grade: g,
    n: cards.filter((c) => c.grade === g).length,
  }));
  return (
    <div className="flex flex-wrap items-center gap-2">
      {counts.map(({ grade, n }) => (
        <span
          key={grade}
          className={`rounded-full px-3 py-1 text-xs font-semibold ${GRADE_STYLE[grade].badge} ${n ? "" : "opacity-40"}`}
        >
          {n} × {grade} · {GRADE_STYLE[grade].label}
        </span>
      ))}
    </div>
  );
}

export function ReportsPage() {
  useDocumentTitle("Economic sentiment — WARN Index");

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
      <PageHeader
        kicker={generatedAt ? `Weekly · updated ${fmtDate(generatedAt)}` : "Weekly"}
        title="Economic sentiment"
        lede={
          <>
            Layoff-trend scorecards for every industry and a national outlook, computed from WARN
            notices (trailing 90 days vs the prior 90). Scores are 0–100, higher is healthier;
            industry figures cover only notices matched to a NAICS code, so treat them as
            directional.
          </>
        }
      />

      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">Industry scorecards</h2>
          {scorecards.data && scorecards.data.length > 0 && <GradeSummary cards={scorecards.data} />}
        </div>
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
        {/* Set as an article: a readable measure, not a full-width card. */}
        <div className="card px-6 py-6 sm:px-10">
          <div className="mx-auto max-w-3xl">
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
