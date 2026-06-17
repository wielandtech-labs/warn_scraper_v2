import { ContentPage } from "./ContentPage";

export function CitedByPage() {
  return (
    <ContentPage
      title="Cited by"
      docTitle="Cited by — WARN Tracker"
      intro="Newsrooms, researchers, and analysts who use WARN Tracker data."
    >
      <p>
        WARN Tracker aggregates official, public layoff filings into one open
        dataset. The data is free to use with attribution — we just ask that you
        link back to <a href="/">warn.wielandtech.com</a> and to the underlying
        state filing where practical.
      </p>

      <h2>Using our data?</h2>
      <p>
        If you've cited WARN Tracker in an article, report, or research project, let
        us know via the <a href="/about">About</a> page and we'll add it here.
      </p>

      <h2>How to cite</h2>
      <p>
        Suggested attribution: “Layoff-notice data via WARN Tracker
        (warn.wielandtech.com), compiled from state WARN Act filings.” See{" "}
        <a href="/methodology">methodology</a> for coverage and limitations, and the{" "}
        <a href="/docs">API docs</a> for programmatic access.
      </p>
    </ContentPage>
  );
}
