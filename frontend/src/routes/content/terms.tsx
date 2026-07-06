import { ContentPage } from "./ContentPage";

export function TermsPage() {
  return (
    <ContentPage
      title="Terms of use"
      docTitle="Terms — WARN Tracker"
      intro="Plain-language terms for the website, API, and datasets."
    >
      <h2>The data</h2>
      <p>
        WARN Tracker compiles layoff and plant-closure notices from public state
        WARN Act filings, then normalizes, deduplicates, geocodes, and
        industry-classifies them. The underlying records are public; our
        value-added fields (stable ids, geocoding, industry classification,
        company attributes) are provided as-is, without warranty of accuracy or
        completeness. Notices are amended by states after filing — figures can
        and do change.
      </p>

      <h2>Website and free API use</h2>
      <ul>
        <li>Browsing the website is free and requires no account.</li>
        <li>
          Programmatic access requires an API key. Free keys have modest rate
          and daily limits; paid tiers raise them. Respect the limits — 429
          responses include a <code>Retry-After</code> header.
        </li>
        <li>
          Attribution is required when publishing work based on this data:
          link to warn.wielandtech.com (see Cited by for examples).
        </li>
      </ul>

      <h2>Paid tiers</h2>
      <ul>
        <li>
          Paid subscriptions unlock enriched company fields (corporate parent
          names, headcounts), bulk exports, and higher limits. Billing is
          handled by Stripe; cancel anytime from your account page.
        </li>
        <li>
          Enriched company fields are licensed for your own use and analysis.
          <strong> Redistributing or reselling the enriched fields as a dataset
          is not permitted</strong> — publish conclusions, not the raw enriched
          columns.
        </li>
        <li>
          Access is per organization, not per key: sharing keys outside your
          organization or proxying the API for third parties requires an
          enterprise agreement.
        </li>
      </ul>

      <h2>Fair use and revocation</h2>
      <p>
        We may throttle or revoke keys that evade rate limits, scrape the
        website to bypass API metering, or violate these terms. We'll contact
        you first when practical.
      </p>

      <h2>No professional advice</h2>
      <p>
        Nothing here is legal, financial, or investment advice. WARN filings
        are noisy, jurisdiction-specific, and frequently amended — verify
        against the linked primary source before relying on any single record.
      </p>

      <h2>Contact</h2>
      <p>
        Questions, enterprise access, or data corrections:{" "}
        <a href="mailto:raphael@wielandtech.com">raphael@wielandtech.com</a>.
      </p>
    </ContentPage>
  );
}
