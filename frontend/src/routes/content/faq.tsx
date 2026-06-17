import { ContentPage } from "./ContentPage";

export function FaqPage() {
  return (
    <ContentPage
      title="Frequently asked questions"
      docTitle="FAQ — WARN Tracker"
    >
      <h2>What is a WARN notice?</h2>
      <p>
        A legally required advance notice that a large employer files before a plant
        closing or mass layoff. See <a href="/warn-act">What is the WARN Act?</a> for
        the full explanation.
      </p>

      <h2>How current is the data?</h2>
      <p>
        We re-scrape every state's WARN listing daily, so new filings usually appear
        within a day of publication. Each notice links to the original state filing.
      </p>

      <h2>Which states are covered?</h2>
      <p>
        All 50 states plus the District of Columbia, wherever the state publishes a
        machine-readable WARN listing. A handful of states restrict or don't publish
        their data; coverage notes live on each <a href="/states">state page</a>.
      </p>

      <h2>Does a notice mean the layoffs definitely happened?</h2>
      <p>
        Not necessarily. A WARN notice signals an <em>intended</em> action; plans can
        change, and filings are sometimes amended or withdrawn. Treat the numbers as a
        leading indicator.
      </p>

      <h2>Can I download the data or use an API?</h2>
      <p>
        Yes — see the <a href="/docs">API documentation</a>. You can also subscribe to
        the <a href="/feed.rss">RSS feed</a> for the latest notices.
      </p>

      <h2>How do you decide a company's industry?</h2>
      <p>
        We attach NAICS/SIC industry codes during enrichment, with a confidence score;
        see <a href="/methodology">methodology</a> for details.
      </p>
    </ContentPage>
  );
}
