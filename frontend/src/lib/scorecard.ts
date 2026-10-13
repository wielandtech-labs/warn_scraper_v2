import type { IndustryScorecard } from "../api/types";

/** A scorecard's 90-day change in workers: "+12%", "new" (from zero), or "—". */
export function deltaCell(card: IndustryScorecard): string {
  if (card.delta_pct === null) {
    return card.cur_layoffs > 0 && card.prior_layoffs === 0 ? "new" : "—";
  }
  return `${card.delta_pct > 0 ? "+" : ""}${Math.round(card.delta_pct)}%`;
}
