import type { RepeatRiskOut } from "../api/types";
import { fmtDate } from "../lib/format";

const MODEL_CARD =
  "https://github.com/wielandtech-labs/warn_scraper_v2/blob/main/docs/ml/repeat-risk-model-card.md";

const TIER: Record<NonNullable<RepeatRiskOut["tier"]>, { label: string; cls: string }> = {
  high: { label: "High", cls: "badge-red" },
  moderate: { label: "Moderate", cls: "badge-amber" },
  low: { label: "Low", cls: "badge-slate" },
};

const pct = (p: number) => `${Math.round(p * 100)}%`;

/** Repeat-filing risk for a company's latest WARN filing. Renders nothing
 *  unless there is something honest to say: a score, or the explicit
 *  "not enough history" for first-time filers. */
export function RepeatRisk({ risk }: { risk: RepeatRiskOut }) {
  if (risk.status !== "scored" && risk.status !== "insufficient_history") return null;
  const through = risk.horizon_end ? fmtDate(risk.horizon_end) : null;

  return (
    <section className="card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">
          Repeat-filing risk
          {risk.tier && (
            <span className={`ml-2 align-middle ${TIER[risk.tier].cls}`}>
              {TIER[risk.tier].label}
            </span>
          )}
        </h2>
        <a
          href={MODEL_CARD}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-sky-700 hover:underline dark:text-sky-400"
        >
          How this is computed
        </a>
      </div>
      {risk.status === "scored" && risk.probability != null ? (
        <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">
          Employers with a filing history like this one filed another WARN notice — more
          job losses — within a year of a filing about{" "}
          <strong>{pct(risk.probability)}</strong> of the time
          {risk.base_rate != null && <> (all employers: {pct(risk.base_rate)})</>}.
          {through && <> This window runs through {through}.</>}
        </p>
      ) : (
        <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">
          Not enough filing history to estimate. This is the first WARN filing we have
          for this employer, and first filings alone barely predict whether more follow.
        </p>
      )}
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        A statistical pattern from past WARN filings, not a forecast of this employer's
        decisions.
      </p>
    </section>
  );
}
