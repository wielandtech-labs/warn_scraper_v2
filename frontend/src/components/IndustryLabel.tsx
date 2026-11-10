import type { CompanyOut } from "../api/types";
import { industryUnverified } from "../lib/industry";

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

/** "SIC code · description", with an Unverified badge when the match isn't exact. */
export function IndustryLabel({
  company: c,
}: {
  company: Pick<CompanyOut, "sic_code" | "sic_desc" | "enrichment_confidence">;
}) {
  if (!c.sic_code) return <>—</>;
  return (
    <>
      {c.sic_desc ? `${c.sic_code} · ${c.sic_desc}` : c.sic_code}
      {industryUnverified(c) && <UnverifiedBadge />}
    </>
  );
}
