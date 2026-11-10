import { industryCode, industryUnverified, type IndustryFields } from "../lib/industry";

export function UnverifiedBadge() {
  return (
    <span
      className="badge-amber ml-2 align-middle"
      title="This company was matched with less than full confidence, so its industry may be wrong."
    >
      Unverified
    </span>
  );
}

/** "code · description", with an Unverified badge when the match isn't exact. */
export function IndustryLabel({ company: c }: { company: IndustryFields }) {
  const ind = industryCode(c);
  if (!ind) return <>—</>;
  return (
    <>
      {ind.desc ? `${ind.code} · ${ind.desc}` : ind.code}
      {ind.system === "SIC" && <span className="text-slate-500 dark:text-slate-400"> (SIC)</span>}
      {industryUnverified(c) && <UnverifiedBadge />}
    </>
  );
}
