import { ContentPage } from "./ContentPage";

export function TermsPage() {
  return (
    <ContentPage
      title="Terms of use"
      docTitle="Terms — WARN Index"
      intro="Plain-language terms for the website, API, and datasets."
    >
      <h2>The data</h2>
      <p>
        WARN Index compiles layoff and plant-closure notices from public state
        WARN Act filings, then normalizes, deduplicates, geocodes, and
        industry-classifies them. The underlying records are public; our
        value-added fields (stable ids, geocoding, industry classification,
        company attributes) are provided as-is, without warranty of accuracy or
        completeness. Notices are amended by states after filing — figures can
        and do change.
      </p>
      <p>
        The website&apos;s source code is open source under the{" "}
        <a href="https://www.gnu.org/licenses/agpl-3.0.html">GNU AGPL-3.0</a>{" "}
        and is <a href="https://github.com/wielandtech-labs/warn_scraper_v2">on GitHub</a>. The data is licensed separately,
        under CC BY 4.0 (below).
      </p>

      <h2>Website and free API use</h2>
      <ul>
        <li>Browsing the website is free and requires no account.</li>
        <li>
          The API is free, with or without a free API key, and is
          rate-limited. Respect the limits — 429
          responses include a <code>Retry-After</code> header.
        </li>
        <li>
          The public data (notice records and the free export&apos;s columns,
          including geocoding and industry codes) is licensed under{" "}
          <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.
          Attribution is required when publishing work based on it: link to
          warnindex.com (see Cited by for examples).
        </li>
      </ul>

      <h2>Separate agreements</h2>
      <p>
        Data or access provided under a separate written agreement is governed
        by that agreement, including any limits it places on redistribution.
      </p>

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
        Questions or data corrections:{" "}
        <a href="mailto:info@warnindex.com">info@warnindex.com</a>.
      </p>
    </ContentPage>
  );
}
