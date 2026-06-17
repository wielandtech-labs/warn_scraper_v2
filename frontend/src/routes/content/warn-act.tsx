import { ContentPage } from "./ContentPage";

export function WarnActPage() {
  return (
    <ContentPage
      title="What is the WARN Act?"
      docTitle="What is the WARN Act? — WARN Tracker"
      intro="A plain-English guide to the federal law behind these layoff notices."
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

      <h2>State "mini-WARN" laws</h2>
      <p>
        Many states have their own WARN-style laws with lower thresholds, longer
        notice periods, or broader coverage than the federal rule — for example
        California, New York, New Jersey, and Illinois. Because notices are filed
        with each state's labor agency, coverage and detail vary by jurisdiction.
        Browse the <a href="/states">per-state pages</a> to see what each one
        publishes.
      </p>

      <h2>What a notice tells you</h2>
      <ul>
        <li>The employer and the affected work site</li>
        <li>How many workers are affected</li>
        <li>Whether it is a layoff or a full closure</li>
        <li>The expected effective date of the separations</li>
      </ul>

      <h2>Limitations of the data</h2>
      <p>
        WARN notices are a <em>leading indicator</em>, not a complete census of job
        loss. Smaller employers, layoffs below the thresholds, and certain
        exceptions (unforeseeable business circumstances, natural disasters) may not
        appear. Filings can also be amended or withdrawn. See our{" "}
        <a href="/methodology">methodology</a> for how we handle these cases.
      </p>
    </ContentPage>
  );
}
