import { ContentPage } from "./ContentPage";

export function ApiDocsPage() {
  return (
    <ContentPage
      title="Data & API access"
      docTitle="Data & API — WARN Tracker"
      intro="Use the WARN Tracker dataset programmatically or as bulk downloads."
    >
      <p>
        All read endpoints are public, return JSON, and live under{" "}
        <code>/api</code>. The full interactive reference (OpenAPI / Swagger) is at{" "}
        <a href="/docs">/docs</a>, and the raw schema at{" "}
        <a href="/openapi.json">/openapi.json</a>.
      </p>

      <h2>Bulk download</h2>
      <p>
        Every notices/companies filter has a matching export that streams the
        whole result set as CSV or JSON:
      </p>
      <ul>
        <li>
          <code>/api/notices/export?format=csv</code> — add any of{" "}
          <code>state</code>, <code>employer</code>, <code>industry</code>,{" "}
          <code>after</code>, <code>before</code>, etc.
        </li>
        <li>
          <code>/api/companies/export?format=json</code>
        </li>
      </ul>
      <p>
        Anonymous downloads are capped to the most recent 1,000 rows. Signed-in
        paid accounts get the full dataset plus enriched company columns.
      </p>

      <h2>Common endpoints</h2>
      <ul>
        <li>
          <code>/api/notices</code> — filter, sort, paginate layoff notices
        </li>
        <li>
          <code>/api/companies</code> — employers, enrichment status, families
        </li>
        <li>
          <code>/api/stats/by-state</code>, <code>by-month</code>,{" "}
          <code>top-employers</code> — aggregates
        </li>
        <li>
          <code>/api/search?q=</code> — company &amp; notice autocomplete
        </li>
      </ul>

      <h2>Feeds</h2>
      <p>
        Subscribe to <a href="/feed.rss">/feed.rss</a> for the latest notices
        site-wide, or <code>/states/&#123;CODE&#125;/feed.rss</code> for one state.
      </p>

      <h2>Terms</h2>
      <p>
        The data is compiled from public state WARN filings; free to use with
        attribution (see <a href="/cited-by">Cited by</a>). Please be reasonable
        with request volume.
      </p>
    </ContentPage>
  );
}
