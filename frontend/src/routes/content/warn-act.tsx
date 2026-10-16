import { ContentPage } from "./ContentPage";

export function WarnActPage() {
  return (
    <ContentPage
      title="What is the Worker Adjustment and Retraining Notification (WARN) Act?"
      docTitle="What is the WARN Act? Guide to Worker Adjustment and Retraining Notification — WARN Index"
      intro="A plain-English guide to the federal Worker Adjustment and Retraining Notification (WARN) Act, 60-day advance notice requirements, and state mini-WARN laws."
    >
      <p>
        The <strong>Worker Adjustment and Retraining Notification (WARN) Act</strong> is
        a 1988 US federal law that requires many employers to give written notice
        at least <strong>60 calendar days</strong> in advance of a covered plant
        closing or mass layoff. The notice goes to affected workers (or their
        representatives), the state's dislocated-worker unit, and the chief elected
        official of the local government.
      </p>

      <h2>Who has to give notice?</h2>
      <p>
        The federal WARN Act generally applies to employers with{" "}
        <strong>100 or more full-time employees</strong>. Notice is triggered by a{" "}
        <strong>plant closing</strong> (a site shutdown affecting 50+ employees) or a{" "}
        <strong>mass layoff</strong> (500+ employees, or 50–499 if they make up at
        least a third of the active workforce at a site).
      </p>

      <h2>State &quot;mini-WARN&quot; laws</h2>
      <p>
        Many states have their own WARN-style laws with lower thresholds, longer
        notice periods, or broader coverage than the federal rule — for example
        California (Cal-WARN), New York, New Jersey, and Illinois. Because notices are filed
        with each state&apos;s labor agency, coverage and detail vary by jurisdiction.
        Browse our <a href="/states">state WARN tracker</a> to see what each state
        publishes.
      </p>
      <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-4 text-sm text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200">
        <p className="font-semibold">Explore the 50-State Mini-WARN Law Guide</p>
        <p className="mt-1 leading-relaxed">
          Need state-specific statutory thresholds, 90-day notice requirements, or New Jersey&apos;s
          mandatory severance pay rules? Compare federal vs. state statutes in our in-depth{" "}
          <a href="/mini-warn-laws" className="font-semibold underline">
            State Mini-WARN Laws Comparison Guide &rarr;
          </a>
        </p>
      </div>

      <h2>What a WARN notice tells you</h2>
      <ul>
        <li>The employer name and affected facility or work site</li>
        <li>How many workers are affected by the layoffs</li>
        <li>Whether the action is a temporary layoff or a permanent plant closure</li>
        <li>The expected effective date of the employee separations</li>
      </ul>

      <h2>Using the WARN Index layoff database</h2>
      <p>
        Because WARN filings are published across dozens of disparate state labor portals,
        WARN Index normalizes every filing into a centralized, searchable{" "}
        <a href="/notices">layoff database</a>. You can use our{" "}
        <a href="/">WARN layoff tracker</a> to search notices in real time, monitor trends across industries,
        or download the entire <a href="/api-docs">WARN dataset</a> for economic research.
      </p>

      <h2>Limitations of the data</h2>
      <p>
        WARN notices are a <em>leading indicator</em>, not a complete census of all US job
        losses. Smaller employers, layoffs below statutory thresholds, and certain
        exceptions (unforeseeable business circumstances, natural disasters) may not
        appear. Filings can also be amended or withdrawn. See our{" "}
        <a href="/methodology">methodology</a> for how we handle these cases.
      </p>
    </ContentPage>
  );
}
