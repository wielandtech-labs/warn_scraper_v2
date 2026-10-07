import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../api/client";
import type { OutlookClaim, OutlookPooled, OutlookTrendRow } from "../api/types";
import { QueryError } from "../components/QueryError";
import { SkeletonRows } from "../components/Skeleton";
import { TBarChart, type TBarRow } from "../components/TBarChart";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtMonth } from "../lib/format";

const Q_GATE = 0.05;
const Z_GATE = 1.96;

const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`;
const ciText = (lo: number, hi: number) => `${signed(lo)} to ${signed(hi)}`;

const CONFIDENCE_STYLE: Record<OutlookClaim["confidence"], string> = {
  high: "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900",
  medium: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100",
  watch: "border border-dashed border-slate-400 text-slate-600 dark:border-slate-500 dark:text-slate-300",
};
const HORIZON_LABEL: Record<OutlookClaim["horizon"], string> = {
  near: "Next 3 months",
  mid: "Next 12 months",
  long: "Scenario input",
};

function Section({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section className="card space-y-3">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {intro && <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{intro}</p>}
      </div>
      {children}
    </section>
  );
}

function ClaimList({ claims }: { claims: OutlookClaim[] }) {
  return (
    <ul className="space-y-2">
      {claims.map((c) => (
        <li key={c.id} className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-3">
          <div className="flex shrink-0 gap-1.5">
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${CONFIDENCE_STYLE[c.confidence]}`}>
              {c.confidence === "watch" ? "watch" : `${c.confidence} confidence`}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-400">
              {HORIZON_LABEL[c.horizon]}
            </span>
          </div>
          <p className="text-sm text-slate-800 dark:text-slate-200">{c.statement}</p>
        </li>
      ))}
    </ul>
  );
}

function PooledTile({ label, pooled, unit }: { label: string; pooled: OutlookPooled; unit: string }) {
  return (
    <div className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">
        {signed(pooled.pct)}
        <span className="ml-1 text-sm font-normal text-slate-500 dark:text-slate-400">{unit}</span>
      </div>
      <div className="text-xs text-slate-500 dark:text-slate-400">
        95% CI {ciText(pooled.ci_lo_pct, pooled.ci_hi_pct)} · {pooled.n_states} states
      </div>
    </div>
  );
}

function trendRows(rows: OutlookTrendRow[], shrunk: boolean): TBarRow[] {
  return rows.map((r) =>
    shrunk && r.shrunk_z !== undefined && r.shrunk_pct !== undefined
      ? {
          code: r.code,
          name: r.name,
          stat: r.shrunk_z,
          effect: `${signed(r.shrunk_pct)}/yr (shrunk)`,
          ci: ciText(r.ci_lo_pct, r.ci_hi_pct) + " raw",
          q: null,
          significant: Math.abs(r.shrunk_z) > Z_GATE,
        }
      : {
          code: r.code,
          name: r.name,
          stat: r.t,
          effect: `${signed(r.pct_per_year)}/yr`,
          ci: ciText(r.ci_lo_pct, r.ci_hi_pct),
          q: r.q,
          significant: r.q < Q_GATE,
        },
  );
}

function ShrinkToggle({ shrunk, onChange }: { shrunk: boolean; onChange: (v: boolean) => void }) {
  const btn = (active: boolean) =>
    `px-3 py-1 text-xs font-medium ${
      active
        ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
        : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
    }`;
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-slate-300 dark:border-slate-700">
      <button type="button" className={btn(!shrunk)} onClick={() => onChange(false)}>
        Raw t-statistics
      </button>
      <button type="button" className={btn(shrunk)} onClick={() => onChange(true)}>
        Shrunk (empirical Bayes)
      </button>
    </div>
  );
}

export function OutlookPage() {
  useDocumentTitle("Layoff outlook — WARN Index");
  const [shrunk, setShrunk] = useState(false);
  const outlook = useQuery({
    queryKey: ["reports", "outlook"],
    queryFn: api.getOutlook,
    retry: (n, error) => !(error instanceof ApiError && error.status === 404) && n < 2,
  });

  if (outlook.isLoading) return <SkeletonRows rows={6} />;
  if (outlook.isError) {
    if (outlook.error instanceof ApiError && outlook.error.status === 404) {
      return (
        <div className="card text-sm text-slate-500 dark:text-slate-400">
          The outlook is computed by a weekly job and will appear after its first run.
        </div>
      );
    }
    return <QueryError message="Error loading the outlook." onRetry={() => outlook.refetch()} />;
  }
  const o = outlook.data!;
  const established = o.claims.filter((c) => c.confidence !== "watch");
  const watch = o.claims.filter((c) => c.confidence === "watch");
  const link = o.unemployment_link;
  const excluded = Object.entries(o.trends.excluded);
  const windowText =
    o.window.first_month && o.window.last_month
      ? `${fmtMonth(o.window.first_month)} – ${fmtMonth(o.window.last_month)}`
      : "—";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Layoff outlook</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600 dark:text-slate-400">
          Forward-looking findings from WARN notices, tested before they are published. A
          finding appears below only when it survives a significance test corrected for the
          number of states and industries tested at once; weaker signals are kept on a
          separate watch list and labelled as such. Updated {fmtDate(o.as_of)}.
        </p>
      </div>

      <Section title="Findings">
        {established.length > 0 ? (
          <ClaimList claims={established} />
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Nothing clears the significance gate this week.
          </p>
        )}
        {watch.length > 0 && (
          <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">Watch list</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Signals worth following that are not yet statistically established.
            </p>
            <ClaimList claims={watch} />
          </div>
        )}
      </Section>

      {link && link.pooled && (
        <Section
          title="Unemployment and layoff filings"
          intro={
            <>
              How WARN filings in each state have moved with that state&apos;s unemployment
              rate: the effect of a 1-point rise in unemployment over the prior year on next
              month&apos;s filings, controlling for trend and season ({fmtMonth(link.first_month)} –{" "}
              {fmtMonth(link.last_month)}). An association, not proof of cause — both respond to
              the same economy.
            </>
          }
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <PooledTile label="Pooled across states" pooled={link.pooled} unit="filings per point" />
            {link.pooled_ex_2020 && (
              <PooledTile label="Excluding 2020–21" pooled={link.pooled_ex_2020} unit="filings per point" />
            )}
          </div>
          <TBarChart
            label="Per-state t-statistics for the unemployment effect on WARN filings"
            rows={link.states.map((r) => ({
              code: r.code,
              name: r.name,
              stat: r.t,
              effect: `${signed(r.pct)} per point`,
              ci: ciText(r.ci_lo_pct, r.ci_hi_pct),
              q: r.q,
              significant: r.q < Q_GATE,
            }))}
          />
        </Section>
      )}

      <Section
        title="Which states are trending"
        intro={
          <>
            Trend in monthly WARN filings over {windowText}, after removing seasonality. Bars
            past the dashed lines are individually significant; red and blue mark the ones that
            stay significant after correcting for testing every state at once. The shrunk view
            pulls noisy small-state estimates toward the national pattern.
          </>
        }
      >
        {o.trends.pooled && (
          <div className="max-w-xs">
            <PooledTile label="Typical state" pooled={o.trends.pooled} unit="per year" />
          </div>
        )}
        <ShrinkToggle shrunk={shrunk} onChange={setShrunk} />
        <TBarChart
          label="Per-state trend t-statistics for WARN filings"
          statLabel={shrunk ? "posterior z" : "t-statistic"}
          rows={trendRows(o.trends.states, shrunk)}
        />
        {excluded.length > 0 && (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Not tested (too little consistent data):{" "}
            {excluded.map(([code, why]) => `${code} (${why})`).join(", ")}.
          </p>
        )}
      </Section>

      {o.sectors.length > 0 && (
        <Section
          title="Industry mix"
          intro="Trend in each industry's share of WARN filings with a known NAICS code. Shares, not counts, because the fraction of notices matched to an industry changes over time."
        >
          <TBarChart
            label="Per-industry trend t-statistics for share of WARN filings"
            statLabel={shrunk ? "posterior z" : "t-statistic"}
            rows={trendRows(o.sectors, shrunk)}
          />
        </Section>
      )}

      <Section title="Method">
        <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600 dark:text-slate-400">
          {Object.entries(o.method).map(([k, v]) => (
            <li key={k}>
              <span className="font-medium">{k.replace(/_/g, " ")}:</span> {String(v)}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
