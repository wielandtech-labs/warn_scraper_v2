import { ContentPage } from "./ContentPage";

export function FaqPage() {
  return (
    <ContentPage
      title="Frequently Asked Questions"
      docTitle="FAQ — WARN Layoff Database & Tracker — WARN Index"
      intro="Answers to common questions about Worker Adjustment and Retraining Notification (WARN) filings, data coverage, and our layoff database."
    >
      <h2>What is a WARN notice?</h2>
      <p>
        A WARN notice is a legally mandated advance notification filed under the federal{" "}
        <a href="/warn-act">Worker Adjustment and Retraining Notification (WARN) Act</a> or state
        mini-WARN laws when an employer plans a plant closing or mass layoff.
      </p>

      <h2>How does the WARN layoff tracker work?</h2>
      <p>
        We run automated scrapers against 50+ US state labor agency websites daily. New filings
        are processed, normalized, and published to our live <a href="/">WARN layoff tracker</a>{" "}
        and searchable <a href="/notices">layoff database</a> usually within 24 hours of state publication.
      </p>

      <h2>Which states are covered in the database?</h2>
      <p>
        We cover all 50 US states and the District of Columbia. See our{" "}
        <a href="/states">layoffs by state</a> directory or the{" "}
        <a href="/status">scraper status page</a> for the live health and update timestamp of every jurisdiction.
      </p>

      <h2>Does a WARN notice mean the layoffs have already occurred?</h2>
      <p>
        No. The WARN Act requires advance notice (typically 60 calendar days) before separations take effect.
        A filing signals planned layoffs or plant closures; dates or numbers can sometimes be amended or withdrawn.
        WARN data serves as a critical <em>leading economic indicator</em> rather than a retrospective count.
      </p>

      <h2>Can I download the WARN dataset or access the API?</h2>
      <p>
        Yes. You can download filtered records or the complete <a href="/api-docs">WARN dataset</a> in CSV or JSON format,
        or integrate our REST API into your workflows. You can also subscribe to our{" "}
        <a href="/feed.rss">RSS feed</a> for real-time notice alerts.
      </p>

      <h2>How are company industries classified?</h2>
      <p>
        We link employers to NAICS and SIC industry codes with machine-assisted validation and confidence scoring;
        see our <a href="/methodology">methodology page</a> for details.
      </p>
    </ContentPage>
  );
}
