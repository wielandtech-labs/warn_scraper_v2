import { ContentPage } from "./ContentPage";

export function MethodologyPage() {
  return (
    <ContentPage
      title="Methodology & data sources"
      docTitle="Methodology & data sources — WARN Tracker"
      intro="How we collect, clean, and enrich the layoff-notice data."
    >
      <h2>Where the data comes from</h2>
      <p>
        Every notice originates from an official <strong>state labor-agency WARN
        listing</strong>. We run automated scrapers against each state's published
        source and store a snapshot of the original filing, linking back to it from
        every record.
      </p>

      <h2>How often it updates</h2>
      <p>
        Scrapers run <strong>daily</strong>. A notice is recorded the first time we
        see it; later runs fill in fields that were initially blank without creating
        duplicates. When a state republishes a corrected filing, the superseded
        record is flagged and excluded from totals.
      </p>

      <h2>Cleaning & de-duplication</h2>
      <ul>
        <li>
          Employer names are normalized (store numbers, "dba" aliases, and facility
          descriptors stripped) so the same company isn't counted under many spellings.
        </li>
        <li>
          Layoffs are categorized as a <strong>closure</strong> or a{" "}
          <strong>layoff</strong> from the state's raw description.
        </li>
        <li>
          Duplicate company records are consolidated, and related entities are grouped
          into corporate families where ownership data supports it.
        </li>
      </ul>

      <h2>Enrichment</h2>
      <p>
        Where possible we attach industry classification (NAICS/SIC), a website, and
        corporate-hierarchy context to each employer, using a tiered cascade of
        public and licensed sources with a confidence score on each match. Low-
        confidence matches are held back rather than shown.
      </p>

      <h2>Geocoding</h2>
      <p>
        Work-site locations are geocoded for the <a href="/map">map</a> using a
        fallback chain — exact address, then ZIP, city, or county centroid — and each
        point records which method produced it. Results outside the filing state are
        rejected.
      </p>

      <h2>Corrections</h2>
      <p>
        Found something wrong? The original state filing linked on each notice is the
        source of truth; let us know via the <a href="/about">About</a> page and we'll
        review it.
      </p>
    </ContentPage>
  );
}
