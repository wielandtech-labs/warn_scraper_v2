import type { CompanyOut } from "../api/types";

/* Industry codes come from the company match. Below an exact match
   (confidence 1.00, MIN_INDUSTRY_CONFIDENCE in warn_v2/companies/naics.py)
   they are often wrong, so the site shows them marked Unverified, and the
   public exports and the Bluesky bot leave them out. No confidence means
   the code came from the filing itself. */
export function industryUnverified(c: Pick<CompanyOut, "enrichment_confidence">): boolean {
  return c.enrichment_confidence != null && Number(c.enrichment_confidence) < 1;
}

export type IndustryFields = Pick<
  CompanyOut,
  "naics_code" | "naics_desc" | "sic_code" | "sic_desc" | "enrichment_confidence"
>;

/** NAICS, like the filters, reports and Bluesky posts; SIC only when a company
    has no NAICS code (about 1% of enriched companies). */
export function industryCode(c: IndustryFields): { code: string; desc: string | null; system: string } | null {
  if (c.naics_code) return { code: c.naics_code, desc: c.naics_desc, system: "NAICS" };
  if (c.sic_code) return { code: c.sic_code, desc: c.sic_desc, system: "SIC" };
  return null;
}
