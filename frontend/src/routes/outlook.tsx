import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../api/client";
import type { OutlookClaim, OutlookPooled, OutlookTrendRow } from "../api/types";
import { ForestPlot, type ForestRow } from "../components/ForestPlot";
import { PageHeader } from "../components/PageHeader";
import { QueryError } from "../components/QueryError";
import { SkeletonRows } from "../components/Skeleton";
import { UsMap } from "../components/UsMap";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useTheme } from "../hooks/useTheme";
import { fmtDate, fmtMonth } from "../lib/format";
import { CHART_COLORS } from "../lib/themeColors";

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
    <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {claims.map((c) => {
        // Trend claims get a direction rule (red = filings rising, blue =
        // easing). The unemployment link is a sensitivity, not a trend, so
        // its sign is not "rising" -- it gets a neutral ink rule.
        const trend = c.kind !== "unemployment_link";
        const rising = c.effect_pct > 0;
        return (
          <li
            key={c.id}
            className={`rounded-xl border border-slate-200 border-l-4 p-4 dark:border-slate-800 ${
              c.confidence === "watch"
                ? "border-l-slate-300 dark:border-l-slate-600"
                : !trend
                  ? "border-l-slate-700 dark:border-l-slate-300"
                  : rising
                  ? "border-l-brand"
                  : "border-l-sky-500"
            }`}
          >
            <div className="flex flex-wrap gap-1.5">
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${CONFIDENCE_STYLE[c.confidence]}`}>
                {c.confidence === "watch" ? "watch" : `${c.confidence} confidence`}
              </span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                {HORIZON_LABEL[c.horizon]}
              </span>
            </div>
            <div className="mt-3 flex items-center gap-4">
              <div className="font-display text-3xl font-semibold tabular-nums text-slate-900 dark:text-slate-50">
                {signed(c.effect_pct)}
              </div>
              <ClaimInterval claim={c} />
            </div>
            <p className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-300">{c.statement}</p>
          </li>
        );
      })}
    </ul>
  );
}

/* A claim's estimate and 95% interval on a small axis centred on zero, so
   "does the interval clear zero?" -- the whole question -- is visible at a
   glance. */
function ClaimInterval({ claim: c }: { claim: OutlookClaim }) {
  const span = Math.max(5, Math.abs(c.ci_lo_pct), Math.abs(c.ci_hi_pct)) * 1.1;
  const x = (v: number) => ((v + span) / (2 * span)) * 100;
  return (
    <div className="min-w-0 flex-1">
      <div aria-hidden className="relative h-4">
        <span className="absolute inset-x-0 top-1/2 h-px bg-slate-200 dark:bg-slate-700" />
        <span className="absolute inset-y-0 left-1/2 border-l border-dashed border-slate-400 dark:border-slate-500" />
        <span
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-slate-400 dark:bg-slate-500"
          style={{ left: `${x(c.ci_lo_pct)}%`, width: `${x(c.ci_hi_pct) - x(c.ci_lo_pct)}%` }}
        />
        <span
          className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-900 ring-2 ring-white dark:bg-slate-100 dark:ring-slate-900"
          style={{ left: `${x(c.effect_pct)}%` }}
        />
      </div>
      <div className="mt-0.5 text-[0.65rem] tabular-nums text-slate-500 dark:text-slate-400">
        95% CI {ciText(c.ci_lo_pct, c.ci_hi_pct)}
      </div>
    </div>
  );
}

/* The state-trend test results on the map: the same colour meaning as the
   bars below (red = significant rise, blue = significant easing), with a
   lighter tint where a state passes its own test but not the correction for
   testing every state. Untested and flat states keep the neutral fill. */
function TrendMap({ rows, shrunk }: { rows: ForestRow[]; shrunk: boolean }) {
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];
  const byCode = new Map(rows.map((r) => [r.code, r]));
  const fills: Record<string, string> = {};
  for (const r of rows) {
    const color = r.est > 0 ? chart.layoffs : chart.notices;
    if (r.significant) fills[r.code] = color;
    else if (r.individually) fills[r.code] = `${color}80`; // ~50% alpha, as in the forest plot
  }
  return (
    <UsMap
      framed={false}
      fills={fills}
      srLabel={`Map of per-state trends in WARN filings${shrunk ? " (shrunk estimates)" : ""}. The chart beside it lists the same states and values.`}
      tooltip={(code) => {
        const r = byCode.get(code);
        if (!r) return <div className="text-slate-500">Not tested</div>;
        return (
          <>
            <div className="font-medium text-slate-900 dark:text-slate-100">{r.name}</div>
            <div className="tabular-nums text-slate-600 dark:text-slate-400">
              {signed(r.est)}/yr · 95% CI {ciText(r.lo, r.hi)}
            </div>
            <div className="text-slate-600 dark:text-slate-400">
              {r.significant
                ? r.est > 0
                  ? "significant rise"
                  : "significant easing"
                : r.individually
                  ? "significant for this state only"
                  : "not significant"}
            </div>
          </>
        );
      }}
      legend={
        <>
          <LegendSwatch color={chart.layoffs} label="Significant rise" />
          <LegendSwatch color={`${chart.layoffs}80`} label="Rising (this state only)" />
          <LegendSwatch color={`${chart.notices}80`} label="Easing (this state only)" />
          <LegendSwatch color={chart.notices} label="Significant easing" />
        </>
      }
    />
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className="h-3 w-3 rounded-sm" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}

function PooledTile({ label, pooled, unit }: { label: string; pooled: OutlookPooled; unit: string }) {
  return (
    <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
      <div className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="mt-1 font-display text-3xl font-semibold tabular-nums">
        {signed(pooled.pct)}
        <span className="ml-1 text-sm font-normal text-slate-500 dark:text-slate-400">{unit}</span>
      </div>
      <div className="text-xs text-slate-500 dark:text-slate-400">
        95% CI {ciText(pooled.ci_lo_pct, pooled.ci_hi_pct)} · {pooled.n_states} states
      </div>
    </div>
  );
}

function trendRows(rows: OutlookTrendRow[], shrunk: boolean): ForestRow[] {
  return rows.map((r) => {
    const base = { code: r.code, name: r.name, lo: r.ci_lo_pct, hi: r.ci_hi_pct };
    return shrunk && r.shrunk_z !== undefined && r.shrunk_pct !== undefined
      ? {
          ...base,
          est: r.shrunk_pct,
          raw: r.pct_per_year,
          stat: r.shrunk_z,
          q: null,
          significant: Math.abs(r.shrunk_z) > Z_GATE,
          individually: Math.abs(r.shrunk_z) > Z_GATE,
        }
      : {
          ...base,
          est: r.pct_per_year,
          stat: r.t,
          q: r.q,
          significant: r.q < Q_GATE,
          individually: Math.abs(r.t) > Z_GATE,
        };
  });
}

function ShrinkToggle({ shrunk, onChange }: { shrunk: boolean; onChange: (v: boolean) => void }) {
  const btn = (active: boolean) =>
    "rounded-full px-3 py-1 text-xs font-medium transition-colors " +
    (active
      ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
      : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100");
  return (
    <div
      role="group"
      aria-label="Estimates"
      className="inline-flex rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900"
    >
      <button type="button" aria-pressed={!shrunk} className={btn(!shrunk)} onClick={() => onChange(false)}>
        Raw estimates
      </button>
      <button type="button" aria-pressed={shrunk} className={btn(shrunk)} onClick={() => onChange(true)}>
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
  const stateRows = trendRows(o.trends.states, shrunk);
  const windowText =
    o.window.first_month && o.window.last_month
      ? `${fmtMonth(o.window.first_month)} – ${fmtMonth(o.window.last_month)}`
      : "—";

  return (
    <div className="space-y-6">
      <PageHeader
        kicker={`Weekly · updated ${fmtDate(o.as_of)}`}
        title="Layoff outlook"
        lede={
          <>
            Forward-looking findings from WARN notices, tested before they are published. A
            finding appears only when it survives a significance test corrected for the number of
            states and industries tested at once; weaker signals sit on a separate, labelled watch
            list.
          </>
        }
        aside={
          <div className="flex gap-6 text-right">
            <div>
              <div className="font-display text-3xl font-semibold tabular-nums">{established.length}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">findings</div>
            </div>
            <div>
              <div className="font-display text-3xl font-semibold tabular-nums text-slate-400">
                {watch.length}
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">on watch</div>
            </div>
          </div>
        }
      />

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
          <ForestPlot
            label="Per-state effect of a 1-point unemployment rise on next month's WARN filings, with 95% confidence intervals"
            unit=" per point"
            rows={link.states.map((r) => ({
              code: r.code,
              name: r.name,
              est: r.pct,
              lo: r.ci_lo_pct,
              hi: r.ci_hi_pct,
              stat: r.t,
              q: r.q,
              significant: r.q < Q_GATE,
              individually: Math.abs(r.t) > Z_GATE,
            }))}
          />
        </Section>
      )}

      <Section
        title="Which states are trending"
        intro={
          <>
            Yearly trend in monthly WARN filings over {windowText}, after removing seasonality,
            with its 95% confidence interval. Solid red and blue mark the states that stay
            significant after correcting for testing every state at once; tints are significant
            on their own test only. The shrunk view pulls noisy small-state estimates toward the
            national pattern (hollow rings show where each started).
          </>
        }
      >
        {o.trends.pooled && (
          <div className="max-w-xs">
            <PooledTile label="Typical state" pooled={o.trends.pooled} unit="per year" />
          </div>
        )}
        <ShrinkToggle shrunk={shrunk} onChange={setShrunk} />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* The map stays in view while the per-state list scrolls past. */}
          <div className="lg:sticky lg:top-20 lg:self-start">
            <TrendMap rows={stateRows} shrunk={shrunk} />
          </div>
          <ForestPlot
            label="Per-state yearly trend in WARN filings, with 95% confidence intervals"
            unit="/yr"
            statLabel={shrunk ? "posterior z" : "t"}
            rows={stateRows}
          />
        </div>
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
          <ForestPlot
            label="Per-industry yearly trend in share of WARN filings, with 95% confidence intervals"
            unit="/yr"
            statLabel={shrunk ? "posterior z" : "t"}
            nameWidth="13rem"
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
