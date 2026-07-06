import { Link } from "@tanstack/react-router";

import { ContentPage } from "./ContentPage";

export function ApiDocsPage() {
  return (
    <ContentPage
      title="Data & API access"
      docTitle="Data & API — WARN Tracker"
      intro="Use the WARN Tracker dataset programmatically or as bulk downloads."
    >
      <p>
        All read endpoints return JSON and live under <code>/api</code>. The
        full interactive reference (OpenAPI / Swagger) is at{" "}
        <a href="/docs">/docs</a>, and the raw schema at{" "}
        <a href="/openapi.json">/openapi.json</a>.
      </p>

      <h2>API keys and tiers</h2>
      <p>
        <Link to="/signup">Create a free account</Link> and mint keys from your{" "}
        <Link to="/account">account page</Link>. Send the key as a header:
      </p>
      <pre className="overflow-x-auto rounded-md bg-slate-100 p-3 text-xs dark:bg-slate-800">
        {`curl -H "X-API-Key: warn_..." \\
  "https://warn.wielandtech.com/api/notices?state=CA&limit=100"`}
      </pre>
      <div className="overflow-x-auto">
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="text-left">
              <th className="py-1 pr-3">&nbsp;</th>
              <th className="py-1 pr-3">Anonymous</th>
              <th className="py-1 pr-3">Free key</th>
              <th className="py-1 pr-3">Paid</th>
              <th className="py-1">Enterprise</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="py-1 pr-3">Burst (per minute)</td>
              <td>120</td>
              <td>120</td>
              <td>600</td>
              <td>600+</td>
            </tr>
            <tr>
              <td className="py-1 pr-3">Requests per day</td>
              <td>—</td>
              <td>2,000</td>
              <td>100,000</td>
              <td>Custom</td>
            </tr>
            <tr>
              <td className="py-1 pr-3">Export rows</td>
              <td>1,000</td>
              <td>10,000</td>
              <td>200,000</td>
              <td>200,000</td>
            </tr>
            <tr>
              <td className="py-1 pr-3">Enriched company fields</td>
              <td>—</td>
              <td>—</td>
              <td>✓</td>
              <td>✓ + identifiers</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        Enriched fields: corporate parent and global-ultimate names, employee
        counts, HQ address. Keyed responses carry <code>X-RateLimit-*</code>{" "}
        headers, and <code>/api/usage</code> reports your quota. Enterprise
        (raw company identifiers, custom quotas, support):{" "}
        <a href="mailto:raphael@wielandtech.com">get in touch</a>.
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
        Anonymous downloads are capped to the most recent 1,000 rows; keyed
        tiers raise the cap per the table above, and paid accounts get the
        enriched company columns.
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
        attribution (see <a href="/cited-by">Cited by</a>). Full terms,
        including what paid tiers may and may not redistribute, are on the{" "}
        <Link to="/terms">Terms of use</Link> page.
      </p>
    </ContentPage>
  );
}
