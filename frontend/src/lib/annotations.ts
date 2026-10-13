// Shaded spans behind the WARN time series, so a spike can be read against
// the economy it landed in. US business-cycle recessions, peak month to trough
// month, per the NBER Business Cycle Dating Committee.
//
// To annotate a notable non-recession event, add a span here: it renders on
// every WARN time chart that covers it.

export interface Span {
  /** "YYYY-MM", inclusive. */
  start: string;
  end: string;
  label: string;
}

export const RECESSIONS: Span[] = [
  { start: "2001-03", end: "2001-11", label: "2001 recession" },
  { start: "2007-12", end: "2009-06", label: "Great Recession" },
  { start: "2020-02", end: "2020-04", label: "COVID-19 recession" },
];

/** Does a chart period ("YYYY", "YYYY-MM" or "YYYY-MM-DD") fall in `span`?
 *  Compared at the period's own granularity, so a year bucket counts as
 *  inside when any of its months are. */
export function periodInSpan(period: string, span: Span): boolean {
  if (period.length === 4) {
    return period >= span.start.slice(0, 4) && period <= span.end.slice(0, 4);
  }
  const month = period.slice(0, 7);
  return month >= span.start && month <= span.end;
}

/** The first and last chart rows inside each span, as x-axis category values
 *  for a Recharts ReferenceArea. Spans the data never reaches are dropped. */
export function spansOnAxis<T extends { period: string }>(
  rows: T[],
  xKey: (row: T) => string,
  spans: Span[] = RECESSIONS,
): { x1: string; x2: string; label: string }[] {
  const out: { x1: string; x2: string; label: string }[] = [];
  for (const span of spans) {
    const inside = rows.filter((r) => periodInSpan(r.period, span));
    if (inside.length === 0) continue;
    out.push({ x1: xKey(inside[0]), x2: xKey(inside[inside.length - 1]), label: span.label });
  }
  return out;
}
