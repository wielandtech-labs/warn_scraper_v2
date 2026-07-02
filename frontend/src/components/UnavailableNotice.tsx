import { stateName } from "../lib/format";
import { LAW_BLOCKED } from "../lib/unavailable";

/**
 * Explainer for states whose WARN notices are withheld by state statute
 * (see LAW_BLOCKED). Rendered on the state detail page in place of the
 * usual (permanently empty) stats.
 */
export function UnavailableNotice({ state }: { state: string }) {
  const info = LAW_BLOCKED[state];
  if (!info) return null;
  const name = stateName(state);

  return (
    <div className="card bg-amber-50">
      <h2 className="text-lg font-semibold">Why is there no {name} data?</h2>
      <p className="mt-2 text-sm text-slate-700">
        Employers in {name} still file federal WARN notices with the {info.agency},
        but under{" "}
        <a
          href={info.statute.url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-sky-700 hover:underline"
        >
          {info.statute.cite}
        </a>{" "}
        those filings are kept confidential. {info.explanation} This is a
        state-law restriction, not a gap in this site&rsquo;s coverage.
      </p>
      <p className="mt-3 text-sm text-slate-700">
        If you live in {name} and think layoff notices should be public record,
        consider contacting your state representative and state senator about{" "}
        {info.statute.cite}:
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        {info.legislatorLinks.map((link) => (
          <li key={link.url}>
            <a
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-sky-700 hover:underline"
            >
              {link.label} →
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
