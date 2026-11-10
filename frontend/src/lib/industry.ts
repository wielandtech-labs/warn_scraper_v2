import type { CompanyOut } from "../api/types";

/* Industry codes come from the company match. Below an exact match
   (confidence 1.00, MIN_INDUSTRY_CONFIDENCE in warn_v2/companies/naics.py)
   they are often wrong, so the site shows them marked Unverified, and the
   public exports and the Bluesky bot leave them out. No confidence means
   the code came from the filing itself. */
export function industryUnverified(c: Pick<CompanyOut, "enrichment_confidence">): boolean {
  return c.enrichment_confidence != null && Number(c.enrichment_confidence) < 1;
}
