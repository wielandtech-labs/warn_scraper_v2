import { useTheme } from "../hooks/useTheme";
import { CHART_COLORS } from "../lib/themeColors";

/* A forest plot: one row per state (or industry), a dot at the estimated
   effect and a whisker for its 95% confidence interval, on a shared % axis
   with a zero line. Effects read in the unit people care about ("+43% a
   year") instead of test statistics, and the whisker shows the uncertainty
   the t-statistic only summarised.

   Colour follows the outlook's verdicts, the same as the trend map: layoffs
   red / notices blue when the row survives the multiple-testing gate, a
   ~35% tint when it is significant on its own test only, neutral otherwise.
   `raw` draws the unshrunk estimate as a hollow ring joined to the shrunk
   dot, so the empirical-Bayes view shows how far each state was pulled.
   Plain HTML/CSS, no chart library; every number is also in the table. */

export interface ForestRow {
  code: string;
  name: string;
  est: number; // % effect (shrunk when `raw` is set)
  lo: number; // 95% CI, % (raw)
  hi: number;
  raw?: number; // unshrunk estimate, shrunk view only
  stat: number; // t (or posterior z)
  q: number | null;
  significant: boolean; // passes the caller's gate
  individually: boolean; // |stat| > 1.96
}

const NEUTRAL = { light: "#c3c2b7", dark: "#52514e" }; // slate-300 / slate-600

const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`;

function verdict(r: ForestRow): string {
  if (r.significant) return r.est > 0 ? "significant rise" : "significant easing";
  if (r.individually) return r.est > 0 ? "rising (this row only)" : "easing (this row only)";
  return "not significant";
}

/** Round-number tick step giving ~4–6 ticks over the span. */
function tickStep(span: number): number {
  const raw = span / 5;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  return (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * mag;
}

export function ForestPlot({
  rows,
  label,
  unit,
  statLabel = "t",
  nameWidth = "7.5rem",
}: {
  rows: ForestRow[];
  label: string;
  unit: string; // appended to effects, e.g. "/yr"
  statLabel?: string;
  nameWidth?: string;
}) {
  const { resolved } = useTheme();
  const chart = CHART_COLORS[resolved];
  const data = rows.slice().sort((a, b) => b.est - a.est);

  // Domain: every interval, but capped at 3x the largest estimate on each
  // side so one very wide interval can't flatten the rest; capped whiskers
  // end in an arrow.
  const maxEst = Math.max(5, ...data.map((r) => Math.abs(r.est)), ...data.map((r) => Math.abs(r.raw ?? 0)));
  const cap = maxEst * 3;
  const min = Math.max(-cap, Math.min(-5, ...data.map((r) => r.lo)));
  const max = Math.min(cap, Math.max(5, ...data.map((r) => r.hi)));
  const step = tickStep(max - min);
  const ticks: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max; t += step) ticks.push(Math.round(t));
  const x = (v: number) => ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * 100;

  const color = (r: ForestRow) => {
    const hue = r.est > 0 ? chart.layoffs : chart.notices;
    return r.significant ? hue : r.individually ? `${hue}80` : NEUTRAL[resolved];
  };

  return (
    <div>
      <div role="img" aria-label={label}>
        <div className="relative">
        {/* Zero line: an overlay spanning every row, in the track column. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 grid gap-2 px-1"
          style={{ gridTemplateColumns: `${nameWidth} 1fr 3.5rem` }}
        >
          <span />
          <span className="relative">
            <span
              className="absolute inset-y-0 border-l border-dashed border-slate-400 dark:border-slate-600"
              style={{ left: `${x(0)}%` }}
            />
          </span>
          <span />
        </div>
        <ul className="relative space-y-px">
          {data.map((r) => {
            const c = color(r);
            const title = `${r.name}: ${signed(r.est)}${unit} (95% CI ${signed(r.lo)} to ${signed(r.hi)}) — ${verdict(r)}`;
            return (
              <li
                key={r.code}
                title={title}
                className="grid items-center gap-2 rounded px-1 text-xs hover:bg-slate-100 dark:hover:bg-slate-800/60"
                style={{ gridTemplateColumns: `${nameWidth} 1fr 3.5rem` }}
              >
                <span className="truncate text-slate-700 dark:text-slate-300">{r.name}</span>
                <span className="relative block h-5">
                  {/* CI whisker */}
                  <span
                    aria-hidden
                    className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full"
                    style={{ left: `${x(r.lo)}%`, width: `${Math.max(0.5, x(r.hi) - x(r.lo))}%`, backgroundColor: c, opacity: 0.55 }}
                  />
                  {r.hi > max && (
                    <span aria-hidden className="absolute right-0 top-1/2 -translate-y-1/2 text-[0.6rem] leading-none" style={{ color: c }}>
                      ▸
                    </span>
                  )}
                  {r.lo < min && (
                    <span aria-hidden className="absolute left-0 top-1/2 -translate-y-1/2 text-[0.6rem] leading-none" style={{ color: c }}>
                      ◂
                    </span>
                  )}
                  {/* Shrinkage: hollow raw estimate joined to the shrunk dot */}
                  {r.raw !== undefined && (
                    <>
                      <span
                        aria-hidden
                        className="absolute top-1/2 h-px -translate-y-1/2 bg-slate-400 dark:bg-slate-500"
                        style={{ left: `${Math.min(x(r.raw), x(r.est))}%`, width: `${Math.abs(x(r.raw) - x(r.est))}%` }}
                      />
                      <span
                        aria-hidden
                        className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-400 bg-white dark:border-slate-500 dark:bg-slate-900"
                        style={{ left: `${x(r.raw)}%` }}
                      />
                    </>
                  )}
                  <span
                    aria-hidden
                    className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-white dark:ring-slate-900"
                    style={{ left: `${x(r.est)}%`, backgroundColor: c }}
                  />
                </span>
                <span className="text-right tabular-nums text-slate-600 dark:text-slate-400">
                  {signed(r.est)}
                </span>
                <span className="sr-only">{title}</span>
              </li>
            );
          })}
        </ul>
        </div>
        {/* Axis: zero line and ticks share the track's coordinates. */}
        <div
          aria-hidden
          className="pointer-events-none relative mt-1 grid gap-2 px-1 text-[0.65rem] text-slate-500 dark:text-slate-400"
          style={{ gridTemplateColumns: `${nameWidth} 1fr 3.5rem` }}
        >
          <span />
          <span className="relative h-4 border-t border-slate-300 dark:border-slate-700">
            {ticks.map((t) => (
              <span key={t} className="absolute top-0.5 -translate-x-1/2 tabular-nums" style={{ left: `${x(t)}%` }}>
                {signed(t)}
              </span>
            ))}
          </span>
          <span />
        </div>
      </div>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-slate-500 dark:text-slate-400">Show table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="min-w-full text-left text-xs">
            <thead className="text-slate-500 dark:text-slate-400">
              <tr>
                <th className="py-1 pr-3">Name</th>
                <th className="py-1 pr-3">Effect</th>
                <th className="py-1 pr-3">95% CI</th>
                <th className="py-1 pr-3">{statLabel}</th>
                <th className="py-1 pr-3">q</th>
                <th className="py-1">Verdict</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {data.map((r) => (
                <tr key={r.code} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-1 pr-3">{r.name}</td>
                  <td className="py-1 pr-3">
                    {signed(r.est)}
                    {unit}
                    {r.raw !== undefined && ` (raw ${signed(r.raw)})`}
                  </td>
                  <td className="py-1 pr-3">
                    {signed(r.lo)} to {signed(r.hi)}
                  </td>
                  <td className="py-1 pr-3">{r.stat.toFixed(2)}</td>
                  <td className="py-1 pr-3">{r.q === null ? "—" : r.q.toFixed(3)}</td>
                  <td className="py-1">{verdict(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
