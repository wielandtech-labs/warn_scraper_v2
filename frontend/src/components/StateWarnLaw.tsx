import { Link } from "@tanstack/react-router";

import { OTHER_STATE_NOTES, STATE_RULES, guideAnchor } from "../lib/stateWarnLaws";

/* The state's own layoff-notice ("mini-WARN") rules on its state page, from
   the same data as the /mini-warn-laws guide. States the guide doesn't cover
   get the federal baseline, worded so it doesn't claim the state has no law
   of its own. */

const FEDERAL = STATE_RULES.find((r) => r.code === "US")!;

export function StateWarnLaw({ code, name }: { code: string; name: string }) {
  const rule = STATE_RULES.find((r) => r.code === code);
  const note = OTHER_STATE_NOTES.find((n) => n.code === code);
  const guide = (
    <Link
      to="/mini-warn-laws"
      hash={rule || note ? guideAnchor(code) : undefined}
      className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
    >
      Compare state WARN laws →
    </Link>
  );

  return (
    <section className="card" aria-labelledby="state-warn-law">
      <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-brand">
        State law
      </p>
      <h2 id="state-warn-law" className="mb-2 mt-1 text-lg font-semibold">
        WARN rules in {name}
      </h2>
      {rule ? (
        <>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {name} has its own layoff-notice law, the {rule.statute}, {rule.statuteCitation},
            on top of the federal WARN Act. Employers follow whichever rule protects workers more.
          </p>
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            {(
              [
                ["Employers covered", rule.employerSize],
                ["Notice required", rule.noticePeriod],
                ["Closings", rule.closureTrigger],
                ["Layoffs", rule.layoffTrigger],
                ["Severance", rule.severanceRequirement],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
                <dd className="text-slate-800 dark:text-slate-200">{value}</dd>
              </div>
            ))}
          </dl>
          <h3 className="mt-4 text-sm font-semibold">How it differs from federal WARN</h3>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700 dark:text-slate-300">
            {rule.keyDifferences.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </>
      ) : note ? (
        <>
          <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{note.title}</p>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{note.note}</p>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            The federal WARN Act applies as well: {FEDERAL.noticePeriod} of notice from employers
            with {FEDERAL.employerSize.toLowerCase()}.
          </p>
        </>
      ) : (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Our state-law guide doesn't cover {name} yet. The federal WARN Act sets the baseline:
          employers with {FEDERAL.employerSize.toLowerCase()} must give{" "}
          {FEDERAL.noticePeriod} of notice before a plant closing affecting{" "}
          {FEDERAL.closureTrigger.toLowerCase()}, or a mass layoff of{" "}
          {FEDERAL.layoffTrigger.toLowerCase()}. Some states add rules of their own; {name}'s labor
          department has the details.
        </p>
      )}
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
        A plain-language summary, not legal advice. {guide}
      </p>
    </section>
  );
}
