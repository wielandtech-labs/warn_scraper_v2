import { useState } from "react";
import { Link } from "@tanstack/react-router";

import { ContentPage } from "./ContentPage";

function CitationBlock({
  label,
  text,
  htmlSnippet,
}: {
  label: string;
  text: string;
  htmlSnippet?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copyTarget = htmlSnippet || text;

  const handleCopy = () => {
    navigator.clipboard.writeText(copyTarget).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-900/50">
      <div className="flex items-center justify-between gap-2 pb-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          {label}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1 rounded-md bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-700"
        >
          {copied ? (
            <span className="text-emerald-600 dark:text-emerald-400">Copied!</span>
          ) : (
            <span>Copy Citation</span>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-xs text-slate-800 dark:text-slate-200">
        {text}
      </pre>
    </div>
  );
}

export function CitedByPage() {
  const webHtmlSnippet =
    'Layoff data provided by <a href="https://warnindex.com">WARN Index</a>, compiled from state WARN Act filings.';

  const bibtex = `@misc{warnindex2026,
  author = {{WARN Index}},
  title = {Nationwide Worker Adjustment and Retraining Notification (WARN) Layoff Dataset},
  year = {2026},
  howpublished = {\\url{https://warnindex.com}},
  note = {Daily aggregated WARN Act filings from 50 US state labor departments}
}`;

  const apa =
    "WARN Index. (2026). Nationwide WARN Act Layoff Dataset & Tracker. Retrieved from https://warnindex.com";

  const mla =
    '"Nationwide WARN Act Layoff Dataset." WARN Index, 2026, https://warnindex.com.';

  const chicago =
    'WARN Index. 2026. "Nationwide WARN Act Layoff Dataset." Accessed 2026. https://warnindex.com.';

  return (
    <ContentPage
      title="Press Kit & Citation Guide"
      docTitle="Press Kit & Citation Guide — Layoff Data for Journalists — WARN Index"
      intro="Resources for journalists, economic reporters, academic researchers, and analysts citing WARN Index layoff data."
      maxWidth="max-w-4xl"
    >
      <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-4 text-sm text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200">
        <p className="font-semibold">Open Access & Media Attribution Policy</p>
        <p className="mt-1 leading-relaxed">
          WARN Index data is open and free to use in journalism, research papers, and market
          commentary. We simply ask for attribution with a link back to{" "}
          <a href="https://warnindex.com" className="font-medium underline">
            warnindex.com
          </a>{" "}
          and, where practical, reference to the underlying state labor department notice.
        </p>
      </div>

      <h2 className="!mt-8 text-xl font-bold">Fast Facts for Newsrooms</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 text-sm">
        <div className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="font-semibold text-slate-900 dark:text-slate-100">50-State + DC Coverage</div>
          <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
            Automated daily scrapers continuously monitor official state workforce and labor department
            portals across the United States.
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="font-semibold text-slate-900 dark:text-slate-100">Leading Economic Indicator</div>
          <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
            WARN filings precede actual separations by 60 to 90 days, providing early signals on workforce
            reductions months before BLS payroll reports.
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="font-semibold text-slate-900 dark:text-slate-100">Normalized Entity Resolution</div>
          <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
            Disparate legal entities and subsidiary names are de-duplicated and linked to parent corporate
            families with SEC and Wikidata cross-references.
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-3.5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="font-semibold text-slate-900 dark:text-slate-100">Standardized NAICS &amp; Geo</div>
          <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
            Every notice is categorized by NAICS sector (tech, healthcare, retail, manufacturing) and
            geocoded with Census street-level and centroid coordinates.
          </p>
        </div>
      </div>

      <h2 className="!mt-8 text-xl font-bold">How to Cite WARN Index</h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Choose the format suitable for your publication or research paper:
      </p>

      <div className="space-y-3">
        <CitationBlock
          label="Digital Journalism / Web Attribution (HTML)"
          text='Layoff data provided by WARN Index (warnindex.com), compiled from state WARN Act filings.'
          htmlSnippet={webHtmlSnippet}
        />

        <CitationBlock label="APA Style (7th Edition)" text={apa} />

        <CitationBlock label="MLA Style (9th Edition)" text={mla} />

        <CitationBlock label="Chicago Manual of Style" text={chicago} />

        <CitationBlock label="BibTeX (Academic & Econometric Research)" text={bibtex} />
      </div>

      <h2 className="!mt-8 text-xl font-bold">Data Access &amp; Tools for Reporters</h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        We provide multiple ways for investigative reporters, beat journalists, and analysts to access our data:
      </p>
      <ul className="text-sm space-y-2">
        <li>
          <strong>Bulk Data Downloads:</strong> Download the entire nationwide dataset as a CSV or JSON file
          from our <Link to="/api-docs">Data &amp; API page</Link>.
        </li>
        <li>
          <strong>Interactive Visualizations:</strong> Explore charts and trends by industry and geography on
          our <Link to="/stats">Trends page</Link> and <Link to="/map">Layoff Map</Link>.
        </li>
        <li>
          <strong>Industry Sentiment Scorecards:</strong> Directional A-through-F layoff health grades across
          all major NAICS industry sectors on our <Link to="/reports">Reports page</Link>.
        </li>
        <li>
          <strong>State Mini-WARN Law Guide:</strong> In-depth statutory comparison of California Cal-WARN,
          New York, New Jersey severance, and other state statutes on our{" "}
          <Link to="/mini-warn-laws">State Mini-WARN Laws Guide</Link>.
        </li>
        <li>
          <strong>Breaking Layoff RSS Feeds:</strong> Subscribe to real-time notifications via our{" "}
          <a href="/feed.rss">National RSS Feed</a> or individual state feeds (e.g. <code>/states/CA/feed.rss</code>).
        </li>
      </ul>

      <h2 className="!mt-8 text-xl font-bold">Media Inquiries &amp; Custom Research Cuts</h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Writing a story on a specific sector, state trend, or corporate layoff wave? We regularly assist
        journalists and academic economists with custom database slices, historical comparisons, and methodology
        walkthroughs.
      </p>
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 text-sm">
        <p className="font-semibold text-slate-900 dark:text-slate-100">Press &amp; Research Contact:</p>
        <p className="mt-1 text-slate-600 dark:text-slate-300">
          Email: <a href="mailto:press@warnindex.com" className="font-medium text-sky-700 underline dark:text-sky-400">press@warnindex.com</a>
        </p>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          We prioritize rapid response for reporters working under breaking news or publishing deadlines.
        </p>
      </div>

      <h2 className="!mt-8 text-xl font-bold">Featured Media &amp; Research Citations</h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        If your newsroom, newsletter, podcast, or academic study has cited WARN Index, let us know via{" "}
        <a href="mailto:press@warnindex.com" className="text-sky-700 underline dark:text-sky-400">
          press@warnindex.com
        </a>{" "}
        or the <Link to="/about">About page</Link> and we will feature your reporting here.
      </p>
    </ContentPage>
  );
}
