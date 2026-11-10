import { Link } from "@tanstack/react-router";

import { ContentPage } from "./ContentPage";

export function ApiDocsPage() {
  return (
    <ContentPage
      title="WARN Dataset & Database API"
      docTitle="WARN Dataset & API — Layoff Database Access — WARN Index"
      intro="Access the complete historical WARN dataset and layoff database programmatically or via bulk CSV and JSON downloads."
    >
      <p>
        The WARN Index provides programmatic and bulk data access to standardized
        Worker Adjustment and Retraining Notification (WARN) filings across all available US
        states. All read endpoints return JSON and live under <code>/api</code>. The
        full interactive reference (OpenAPI / Swagger) is at{" "}
        <a href="/docs">/docs</a>, and the raw schema at{" "}
        <a href="/openapi.json">/openapi.json</a>.
      </p>

      <h2>Free API keys and limits</h2>
      <p>
        The API is free. Anonymous requests work without signing up; for a
        daily quota of your own,{" "}
        <Link to="/signup">create a free account</Link> and mint keys from your{" "}
        <Link to="/account">account page</Link>. Send the key as a header:
      </p>
      <pre className="overflow-x-auto rounded-md bg-slate-100 p-3 text-xs dark:bg-slate-800">
        {`curl -H "X-API-Key: warn_..." \\
  "https://warnindex.com/api/notices?state=CA&limit=100"`}
      </pre>
      <div className="overflow-x-auto">
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="text-left">
              <th className="py-1 pr-3">&nbsp;</th>
              <th className="py-1 pr-3">Anonymous</th>
              <th className="py-1">Free key</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="py-1 pr-3">Burst (per minute)</td>
              <td>120</td>
              <td>120</td>
            </tr>
            <tr>
              <td className="py-1 pr-3">Requests per day</td>
              <td>—</td>
              <td>2,000</td>
            </tr>
            <tr>
              <td className="py-1 pr-3">Export rows</td>
              <td>1,000</td>
              <td>1,000</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        Keyed responses carry <code>X-RateLimit-*</code> headers, and{" "}
        <code>/api/usage</code> reports your quota. Need the whole dataset? Skip
        the API and grab the free bulk snapshot below.
      </p>

      <h2>Bulk WARN dataset download</h2>
      <p>
        <strong>Full dataset, no key needed:</strong> a weekly snapshot of every
        notice (public columns, Parquet and gzipped CSV, CC BY 4.0) is mirrored on 
        <a href="https://huggingface.co/datasets/warn-index/us-warn-layoffs">Hugging Face</a>. Load it with 
        <code>load_dataset("warn-index/us-warn-layoffs")</code> or download the
        files directly. The same snapshot, with column descriptions, is on{" "}
        <a href="https://www.kaggle.com/datasets/warnindex/us-warn-act-layoff-notices-1989-2026">Kaggle</a>{" "}
        for use in Kaggle notebooks. The{" "}
        <a href="https://www.kaggle.com/writeups/warnindex/warn-index-every-us-layoff-notice-in-one-dataset">project writeup</a>{" "}
        explains how the dataset is built and what it shows.
      </p>
      <p>
        Researchers, analysts, and engineering teams can export records from our
        nationwide layoff database. Every notices/companies filter has a matching export
        that streams the result set as CSV or JSON:
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
        Exports are capped to the most recent 1,000 rows; for everything, use
        the Hugging Face snapshot above.
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
        Large new notices are also posted to{" "}
        <a href="https://bsky.app/profile/warnindex.com">@warnindex.com on Bluesky</a>.
      </p>

      <h2>Terms</h2>
      <p>
        The data is compiled from public state WARN filings and licensed under{" "}
        <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>: free
        to use with attribution (see <a href="/cited-by">Cited by</a>). Full terms
        are on the{" "}
        <Link to="/terms">Terms of use</Link> page.
      </p>
    </ContentPage>
  );
}
