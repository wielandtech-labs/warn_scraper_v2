import { fmtDate } from "../lib/format";

/** Footnote under a time-series chart explaining the dashed pace projection. */
export function ProjectionNote({ periodLabel }: { periodLabel: string }) {
  const todayIso = new Date().toISOString().slice(0, 10);
  return (
    <p className="mt-2 text-xs text-slate-500">
      Dashed segment: {periodLabel} is projected from data reported through{" "}
      {fmtDate(todayIso)}.
    </p>
  );
}
