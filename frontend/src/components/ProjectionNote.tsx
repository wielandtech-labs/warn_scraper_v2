/** Footnote under a time-series chart explaining the dashed pace projection. */
export function ProjectionNote({ periodLabel }: { periodLabel: string }) {
  // Local date, not UTC — an evening viewer west of Greenwich shouldn't read
  // "data reported through <tomorrow>".
  const today = new Date().toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  return (
    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
      Dashed segment: {periodLabel} is projected from data reported through{" "}
      {today}.
    </p>
  );
}
