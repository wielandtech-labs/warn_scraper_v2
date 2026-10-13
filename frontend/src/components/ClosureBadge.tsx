/* Only the exceptions are badged: a plain layoff is the default and a badge
   on every row would be noise. Closures (the whole site goes) stand out;
   Non-WARN rows (state rapid-response events, not statutory notices) are
   visibly set apart. */
export function ClosureBadge({ category }: { category: string | null }) {
  if (category !== "Closure" && category !== "Non-WARN") return null;
  const style =
    category === "Closure"
      ? "bg-brand/10 text-brand dark:bg-brand/20 dark:text-brand-dark"
      : "border border-dashed border-slate-300 text-slate-500 dark:border-slate-600 dark:text-slate-400";
  return (
    <span className={`rounded-full px-2 py-px text-[0.65rem] font-semibold uppercase tracking-wide ${style}`}>
      {category}
    </span>
  );
}
