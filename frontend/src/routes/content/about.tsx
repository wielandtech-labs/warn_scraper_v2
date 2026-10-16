import { ContentPage } from "./ContentPage";

export function AboutPage() {
  return (
    <ContentPage
      title="About WARN Index"
      docTitle="About WARN Index — US Layoff Tracker & Database"
      intro="A nationwide, daily-updated WARN layoff tracker and standardized database of US worker adjustments and plant closures."
    >
      <p>
        <strong>WARN Index</strong> collects, standardizes, and publishes layoff notices
        filed under the federal{" "}
        <a href="/warn-act">Worker Adjustment and Retraining Notification (WARN) Act</a> and
        state &quot;mini-WARN&quot; laws across all 50 US states and DC. We turn fragmented state
        filings into a unified <a href="/notices">layoff database</a> that is freely searchable,
        mappable, and downloadable as a <a href="/api-docs">WARN dataset</a>.
      </p>

      <h2>Why the WARN layoff tracker exists</h2>
      <p>
        Advance notice filings under the WARN Act are public records, but they are scattered
        across dozens of separate state labor department portals in inconsistent formats (HTML
        tables, PDFs, Excel sheets). We bring them together — de-duplicated, categorized, geocoded,
        and enriched with corporate family groupings and industry classifications — so
        journalists, economic researchers, workforce analysts, and impacted employees can track
        layoffs across the United States in real time.
      </p>

      <h2>How the layoff database works</h2>
      <p>
        Automated scrapers pull each state labor agency&apos;s WARN listings daily; our processing
        pipeline cleans, validates, and geocodes each notice. The complete data model and pipeline
        are documented on our <a href="/methodology">methodology page</a>.
      </p>

      <h2>Get in touch</h2>
      <p>
        Spotted an error, have a feature request, or using our WARN dataset in your research or reporting?
        We&apos;d love to hear from you — email{" "}
        <a href="mailto:contact@wielandtech.com">contact@wielandtech.com</a>.
      </p>
    </ContentPage>
  );
}
