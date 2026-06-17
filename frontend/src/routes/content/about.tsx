import { ContentPage } from "./ContentPage";

export function AboutPage() {
  return (
    <ContentPage
      title="About WARN Tracker"
      docTitle="About — WARN Tracker"
      intro="A free, searchable database of US layoff and plant-closure notices."
    >
      <p>
        WARN Tracker collects layoff and closure notices filed under the federal{" "}
        <a href="/warn-act">WARN Act</a> and state "mini-WARN" laws, standardizes them
        into one dataset, and makes them searchable, mappable, and downloadable.
      </p>

      <h2>Why it exists</h2>
      <p>
        WARN notices are public, but they're scattered across dozens of state agency
        pages in inconsistent formats. We bring them together — de-duplicated,
        categorized, geocoded, and enriched with industry and company context — so
        journalists, researchers, policymakers, and affected workers can see what's
        happening across the whole country in one place.
      </p>

      <h2>How it works</h2>
      <p>
        Automated scrapers pull each state's WARN listing daily; a processing pipeline
        cleans and links the records. The full approach is documented on the{" "}
        <a href="/methodology">methodology</a> page.
      </p>

      <h2>Get in touch</h2>
      <p>
        Spotted an error, or using the data in your work? We'd like to hear about it —
        email <a href="mailto:contact@wielandtech.com">contact@wielandtech.com</a>.
      </p>
    </ContentPage>
  );
}
