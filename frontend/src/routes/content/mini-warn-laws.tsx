import { ContentPage } from "./ContentPage";

interface StateRule {
  state: string;
  code: string;
  statute: string;
  statuteCitation: string;
  employerSize: string;
  noticePeriod: string;
  closureTrigger: string;
  layoffTrigger: string;
  severanceRequirement: string;
  keyDifferences: string[];
}

const STATE_RULES: StateRule[] = [
  {
    state: "Federal WARN Act",
    code: "US",
    statute: "Worker Adjustment and Retraining Notification Act",
    statuteCitation: "29 U.S.C. §§ 2101–2109",
    employerSize: "100+ full-time employees",
    noticePeriod: "60 calendar days",
    closureTrigger: "50+ full-time employees at a single site",
    layoffTrigger: "500+ employees, or 50–499 if 33%+ of workforce",
    severanceRequirement: "None mandated (penalties for non-compliance)",
    keyDifferences: [
      "Baseline federal standard across all US jurisdictions",
      "Only counts full-time employees (worked 6+ of last 12 months, 20+ hrs/wk)",
      "Single site of employment rule",
    ],
  },
  {
    state: "California",
    code: "CA",
    statute: "California WARN Act (Cal-WARN)",
    statuteCitation: "Cal. Lab. Code §§ 1400–1408",
    employerSize: "75+ persons in past 12 months (includes part-time)",
    noticePeriod: "60 calendar days",
    closureTrigger: "Cessation or substantial cessation of industrial/commercial operations",
    layoffTrigger: "50+ employees in 30 days regardless of percentage",
    severanceRequirement: "None mandated by statute",
    keyDifferences: [
      "Lower threshold: 75 employees vs. 100 federal",
      "No 33% threshold rule: 50 layoffs always triggers notice",
      "Covers relocations of 100+ miles",
      "Counts part-time employees toward employer coverage threshold",
    ],
  },
  {
    state: "New York",
    code: "NY",
    statute: "New York State WARN Act",
    statuteCitation: "N.Y. Lab. Law §§ 860-a to 860-m; 12 NYCRR Part 921",
    employerSize: "50+ full-time employees",
    noticePeriod: "90 calendar days",
    closureTrigger: "25+ employees affected at a single site",
    layoffTrigger: "250+ employees, or 25–249 if 33%+ of workforce",
    severanceRequirement: "None mandated by statute",
    keyDifferences: [
      "90 days notice required (30 days longer than federal)",
      "Applies to smaller employers (50+ employees vs. 100 federal)",
      "Triggers at just 25 affected workers for plant closings",
      "Also triggered by relocation (50+ miles) or 50%+ reduction in hours",
    ],
  },
  {
    state: "New Jersey",
    code: "NJ",
    statute: "Millville Dallas Airmotive Plant Loss Notification Act",
    statuteCitation: "N.J. Stat. Ann. § 34:21-1 et seq.",
    employerSize: "100+ employees nationwide (full-time & part-time)",
    noticePeriod: "90 calendar days",
    closureTrigger: "Transfer or termination of operations affecting 50+ employees",
    layoffTrigger: "50+ employees across the state in a 30-day or 90-day window",
    severanceRequirement: "Mandatory: 1 week pay per year of service (+4 weeks penalty)",
    keyDifferences: [
      "First state with mandatory severance: 1 week of pay per year of service",
      "Additional 4 weeks severance penalty if employer fails to provide 90 days notice",
      "90 days notice (vs. 60 days federal)",
      "Statewide aggregation: 50 layoffs anywhere in NJ triggers WARN, not single-site",
      "Applies to part-time workers equally",
    ],
  },
  {
    state: "Illinois",
    code: "IL",
    statute: "Illinois Worker Adjustment and Retraining Notification Act",
    statuteCitation: "820 ILCS 65/1 et seq.",
    employerSize: "75+ full-time employees",
    noticePeriod: "60 calendar days",
    closureTrigger: "50+ full-time employees at a single site",
    layoffTrigger: "250+ employees, or 25–249 if 33%+ of workforce",
    severanceRequirement: "None mandated by statute",
    keyDifferences: [
      "75-employee coverage threshold (vs. 100 federal)",
      "Lower mass layoff threshold (250 employees vs. 500 federal)",
      "Notice must be served to local commerce commission and municipalities",
    ],
  },
  {
    state: "Hawaii",
    code: "HI",
    statute: "Hawaii Dislocated Workers Act",
    statuteCitation: "Haw. Rev. Stat. §§ 394B-1 to 394B-13",
    employerSize: "50+ employees in preceding 12 months",
    noticePeriod: "60 calendar days",
    closureTrigger: "Closing, partial closing, or relocation of a covered facility",
    layoffTrigger: "Any covered closing or transaction resulting in dislocated workers",
    severanceRequirement: "Dislocated worker allowance required under certain conditions",
    keyDifferences: [
      "Applies to employers with 50+ employees",
      "Covers partial closings and business sales/transfers",
      "Requires supplemental dislocated worker benefit allowance",
    ],
  },
  {
    state: "Wisconsin",
    code: "WI",
    statute: "Wisconsin Business Closing and Mass Layoff Law",
    statuteCitation: "Wis. Stat. § 109.07; DWD 279",
    employerSize: "50+ employees in Wisconsin",
    noticePeriod: "60 calendar days",
    closureTrigger: "Permanent or temporary shutdown affecting 25+ employees",
    layoffTrigger: "At least 25% of workforce OR 25 employees (whichever is greater), or 500+ employees",
    severanceRequirement: "None mandated by statute",
    keyDifferences: [
      "50-employee threshold (vs. 100 federal)",
      "Closure triggered by just 25 affected employees",
      "Mass layoff trigger as low as 25 employees if 25% of site",
    ],
  },
  {
    state: "Maine",
    code: "ME",
    statute: "Maine Severance Pay Act",
    statuteCitation: "Me. Rev. Stat. Ann. tit. 26, § 625-B",
    employerSize: "100+ persons at any time in past 12 months",
    noticePeriod: "90 calendar days",
    closureTrigger: "Cessation of operations or relocation 100+ miles away",
    layoffTrigger: "Termination or closing affecting covered establishment",
    severanceRequirement: "Mandatory: 1 week pay per year of service for closures/relocations",
    keyDifferences: [
      "90 days advance notice to director, municipal officers, and employees",
      "Mandatory severance of 1 week per year of service at covered facility",
      "Strict liability for failure to pay severance within one regular pay period",
    ],
  },
];

export function MiniWarnLawsPage() {
  return (
    <ContentPage
      title="State Mini-WARN Act Laws: Complete 50-State Guide & Comparison"
      docTitle="State Mini-WARN Act Guide — California, New York, New Jersey & State Layoff Laws — WARN Index"
      intro="A comprehensive guide to state 'mini-WARN' layoff statutes. Compare employer thresholds, 90-day advance notice requirements, mandatory severance rules, and how state laws expand beyond the federal WARN Act."
      maxWidth="max-w-5xl"
    >
      <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-4 text-sm text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200">
        <p className="font-semibold">Key Takeaway for Employers, HR, and Workers</p>
        <p className="mt-1 leading-relaxed">
          While the federal WARN Act sets a nationwide baseline (100+ employees, 60-day notice),
          individual states have enacted <strong>mini-WARN laws</strong> with far stricter
          rules. Some states require <strong>90 days advance notice</strong> (New York, New Jersey, Maine),
          lower threshold employer sizes down to <strong>50 employees</strong>, or mandate{" "}
          <strong>compulsory severance pay</strong> (New Jersey, Maine). Employers must comply with
          whichever law provides greater protection to workers.
        </p>
      </div>

      <nav aria-label="Jump to state" className="my-6 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Jump to:
        </span>
        <a
          href="#comparison-matrix"
          className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          Comparison Table
        </a>
        <a
          href="#california"
          className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          California (Cal-WARN)
        </a>
        <a
          href="#new-york"
          className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          New York
        </a>
        <a
          href="#new-jersey"
          className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          New Jersey (Severance)
        </a>
        <a
          href="#illinois"
          className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          Illinois
        </a>
        <a
          href="#other-states"
          className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          Other States
        </a>
        <a
          href="#mini-warn-faq"
          className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          FAQ
        </a>
      </nav>

      <h2 id="comparison-matrix" className="!mt-8 text-2xl font-bold">
        State Mini-WARN Laws vs. Federal WARN: Quick Comparison Table
      </h2>
      <p>
        The table below highlights statutory thresholds, advance notice windows, and severance
        mandates across the most prominent state layoff notice laws.
      </p>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <table className="w-full min-w-[700px] border-collapse text-left text-xs sm:text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950/60">
              <th className="p-3 font-semibold text-slate-900 dark:text-slate-100">Jurisdiction</th>
              <th className="p-3 font-semibold text-slate-900 dark:text-slate-100">Employer Size</th>
              <th className="p-3 font-semibold text-slate-900 dark:text-slate-100">Notice Period</th>
              <th className="p-3 font-semibold text-slate-900 dark:text-slate-100">Closure Trigger</th>
              <th className="p-3 font-semibold text-slate-900 dark:text-slate-100">Layoff Trigger</th>
              <th className="p-3 font-semibold text-slate-900 dark:text-slate-100">Severance Mandate</th>
              <th className="p-3 font-semibold text-slate-900 dark:text-slate-100">Layoff Tracker</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {STATE_RULES.map((rule) => (
              <tr key={rule.code} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30">
                <td className="p-3 font-medium text-slate-900 dark:text-slate-100">
                  <div className="font-semibold">{rule.state}</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">{rule.statuteCitation}</div>
                </td>
                <td className="p-3">{rule.employerSize}</td>
                <td className="p-3">
                  <span
                    className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${
                      rule.noticePeriod.includes("90")
                        ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                        : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                    }`}
                  >
                    {rule.noticePeriod}
                  </span>
                </td>
                <td className="p-3">{rule.closureTrigger}</td>
                <td className="p-3">{rule.layoffTrigger}</td>
                <td className="p-3">
                  <span
                    className={`text-xs ${
                      rule.severanceRequirement.includes("Mandatory")
                        ? "font-semibold text-rose-600 dark:text-rose-400"
                        : "text-slate-500 dark:text-slate-400"
                    }`}
                  >
                    {rule.severanceRequirement}
                  </span>
                </td>
                <td className="p-3 whitespace-nowrap">
                  {rule.code === "US" ? (
                    <a href="/notices" className="font-medium text-sky-700 hover:underline dark:text-sky-400">
                      All Notices &rarr;
                    </a>
                  ) : (
                    <a
                      href={`/states/${rule.code}`}
                      className="font-medium text-sky-700 hover:underline dark:text-sky-400"
                    >
                      {rule.code} Notices &rarr;
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 id="deep-dives" className="!mt-10 text-2xl font-bold">
        Detailed State Mini-WARN Profiles
      </h2>

      {/* California */}
      <section id="california" className="card mt-6 space-y-3 p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-200 pb-3 dark:border-slate-800">
          <h3 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            California Cal-WARN Act (Labor Code §§ 1400–1408)
          </h3>
          <a
            href="/states/CA"
            className="text-xs font-semibold uppercase tracking-wider text-sky-700 hover:underline dark:text-sky-400"
          >
            Track California WARN Notices &rarr;
          </a>
        </div>
        <p>
          California&apos;s mini-WARN law (Cal-WARN) is one of the most frequently litigated state
          statutes in the nation. It covers any &quot;covered establishment&quot; that has employed{" "}
          <strong>75 or more persons</strong> (including part-time workers) within the preceding 12
          months.
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 text-sm">
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
            <span className="font-semibold text-slate-900 dark:text-slate-100">Mass Layoff Trigger:</span>
            <p className="mt-1 text-slate-600 dark:text-slate-300">
              Separation of <strong>50 or more employees</strong> during any 30-day period. Crucially,
              unlike the federal WARN Act, there is <em>no percentage requirement</em> (such as the 33%
              federal rule).
            </p>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
            <span className="font-semibold text-slate-900 dark:text-slate-100">Relocation Trigger:</span>
            <p className="mt-1 text-slate-600 dark:text-slate-300">
              Moving all or part of an operation <strong>100 miles or more</strong> away requires a full
              60-day Cal-WARN notice, even if workers are offered transfer opportunities.
            </p>
          </div>
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          <strong>Notice Recipients:</strong> Affected employees, the California Employment Development
          Department (EDD), the local Workforce Development Board, and the chief elected official of the
          city and county.
        </p>
      </section>

      {/* New York */}
      <section id="new-york" className="card mt-6 space-y-3 p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-200 pb-3 dark:border-slate-800">
          <h3 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            New York State WARN Act (N.Y. Lab. Law §§ 860-a to 860-m)
          </h3>
          <a
            href="/states/NY"
            className="text-xs font-semibold uppercase tracking-wider text-sky-700 hover:underline dark:text-sky-400"
          >
            Track New York WARN Notices &rarr;
          </a>
        </div>
        <p>
          New York significantly expands worker protections by mandating a{" "}
          <strong className="text-amber-800 dark:text-amber-300">90 calendar day advance notice period</strong>
          — a full month longer than federal law. It also lowers employer coverage from 100 to{" "}
          <strong>50 full-time employees</strong>.
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 text-sm">
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
            <span className="font-semibold text-slate-900 dark:text-slate-100">Plant Closing:</span>
            <p className="mt-1 text-slate-600 dark:text-slate-300">
              Affects <strong>25 or more employees</strong> at a single site of employment.
            </p>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
            <span className="font-semibold text-slate-900 dark:text-slate-100">Mass Layoff:</span>
            <p className="mt-1 text-slate-600 dark:text-slate-300">
              Affects <strong>250+ employees</strong>, or <strong>25–249 employees</strong> if they
              comprise at least 33% of the workforce.
            </p>
          </div>
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
            <span className="font-semibold text-slate-900 dark:text-slate-100">Hours Reduction:</span>
            <p className="mt-1 text-slate-600 dark:text-slate-300">
              A reduction of hours of more than 50% for 25+ employees over 6 months triggers WARN.
            </p>
          </div>
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          <strong>Remote Worker Regulations:</strong> Recent NY regulations clarify that remote employees
          who report to or are assigned to a New York operational site count toward employment thresholds.
        </p>
      </section>

      {/* New Jersey */}
      <section id="new-jersey" className="card mt-6 space-y-3 p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-200 pb-3 dark:border-slate-800">
          <h3 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            New Jersey WARN Act (N.J. Stat. Ann. § 34:21-1 et seq.)
          </h3>
          <a
            href="/states/NJ"
            className="text-xs font-semibold uppercase tracking-wider text-sky-700 hover:underline dark:text-sky-400"
          >
            Track New Jersey WARN Notices &rarr;
          </a>
        </div>
        <div className="rounded-lg border border-rose-300 bg-rose-50/70 p-3 text-xs text-rose-900 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200">
          <strong>Mandatory Severance State:</strong> New Jersey is the first and only state to mandate
          statutory severance pay for covered layoffs, regardless of company policy or employment agreements.
        </div>
        <p>
          Following sweeping amendments, New Jersey&apos;s law imposes some of the strictest layoff
          compliance standards in the world:
        </p>
        <ul className="space-y-2 text-sm">
          <li>
            <strong>Mandatory Severance:</strong> Employers must pay affected employees{" "}
            <strong>one week of severance pay for every full year of employment</strong>.
          </li>
          <li>
            <strong>Failure-to-Notice Penalty:</strong> If an employer provides less than the required{" "}
            <strong>90 days advance notice</strong>, it must pay an{" "}
            <strong className="text-rose-600 dark:text-rose-400">additional 4 weeks of severance pay</strong>{" "}
            to every affected employee.
          </li>
          <li>
            <strong>Statewide Aggregation:</strong> Layoffs are no longer evaluated site-by-site. If an
            employer terminates <strong>50 or more employees across all New Jersey facilities</strong>{" "}
            combined in a 30-day (or 90-day) window, the statute is triggered.
          </li>
          <li>
            <strong>All Workers Count:</strong> Part-time workers and full-time workers are treated
            identically when assessing coverage thresholds.
          </li>
        </ul>
      </section>

      {/* Illinois */}
      <section id="illinois" className="card mt-6 space-y-3 p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-200 pb-3 dark:border-slate-800">
          <h3 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            Illinois WARN Act (820 ILCS 65/)
          </h3>
          <a
            href="/states/IL"
            className="text-xs font-semibold uppercase tracking-wider text-sky-700 hover:underline dark:text-sky-400"
          >
            Track Illinois WARN Notices &rarr;
          </a>
        </div>
        <p>
          Illinois enforces a 60-day notice window but lowers the threshold for covered employers to{" "}
          <strong>75 full-time employees</strong> (compared to 100 under federal law).
        </p>
        <ul className="space-y-1 text-sm">
          <li>
            <strong>Plant Closing:</strong> 50 or more workers during any 30-day period.
          </li>
          <li>
            <strong>Mass Layoff:</strong> 250 or more full-time workers, or 25–249 workers if they
            represent at least 33% of the workforce at the facility.
          </li>
          <li>
            <strong>Notice Recipient Requirements:</strong> Notice must be filed with the Illinois
            Department of Commerce and Economic Opportunity (DCEO), affected workers, union
            representatives, and the chief elected municipal and county officials.
          </li>
        </ul>
      </section>

      {/* Other States */}
      <section id="other-states" className="card mt-6 space-y-3 p-6">
        <h3 className="text-xl font-semibold text-slate-900 dark:text-slate-100 border-b border-slate-200 pb-3 dark:border-slate-800">
          Other States with Notable Mini-WARN or Layoff Notice Provisions
        </h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 text-sm">
          <div className="space-y-1 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/40">
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              <a href="/states/ME" className="hover:underline">Maine (26 M.R.S. § 625-B)</a>
            </h4>
            <p className="text-xs text-slate-600 dark:text-slate-300">
              Requires <strong>90 days notice</strong> for plant closures or relocations 100+ miles away for
              employers with 100+ workers. Mandates <strong>1 week of severance pay per year of service</strong>{" "}
              for employees with 3+ years of tenure.
            </p>
          </div>
          <div className="space-y-1 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/40">
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              <a href="/states/WI" className="hover:underline">Wisconsin (Wis. Stat. § 109.07)</a>
            </h4>
            <p className="text-xs text-slate-600 dark:text-slate-300">
              Applies to employers with 50+ workers. Requires 60 days notice if a business closing affects
              25+ workers, or if a mass layoff affects 25+ workers comprising 25% of the workforce.
            </p>
          </div>
          <div className="space-y-1 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/40">
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              <a href="/states/HI" className="hover:underline">Hawaii (Haw. Rev. Stat. § 394B)</a>
            </h4>
            <p className="text-xs text-slate-600 dark:text-slate-300">
              Covers employers with 50+ workers. Mandates 60 days notice for closings, partial closings, or
              relocations, and provides a statutory dislocated worker benefit allowance.
            </p>
          </div>
          <div className="space-y-1 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/40">
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              <a href="/states/CT" className="hover:underline">Connecticut (Conn. Gen. Stat. § 31-51o)</a>
            </h4>
            <p className="text-xs text-slate-600 dark:text-slate-300">
              Requires employers with 100+ workers closing or relocating an establishment to pay for
              continued group health insurance coverage for affected employees for up to 120 days.
            </p>
          </div>
          <div className="space-y-1 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/40">
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              <a href="/states/MD" className="hover:underline">Maryland (Labor &amp; Empl. § 11-301)</a>
            </h4>
            <p className="text-xs text-slate-600 dark:text-slate-300">
              Mandatory 60 days notice for employers with 50+ employees reducing operations by at least
              25% or 15 employees (whichever is greater).
            </p>
          </div>
          <div className="space-y-1 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/40">
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              <a href="/states/TN" className="hover:underline">Tennessee (Tenn. Code § 50-1-601)</a>
            </h4>
            <p className="text-xs text-slate-600 dark:text-slate-300">
              Covers employers with 50–99 employees who are not covered under federal WARN, requiring
              notification to the state labor department.
            </p>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <h2 id="mini-warn-faq" className="!mt-10 text-2xl font-bold">
        Frequently Asked Questions: State Mini-WARN Laws
      </h2>

      <div className="space-y-4">
        <div>
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">
            Does a state mini-WARN law replace the federal WARN Act?
          </h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            No. State mini-WARN laws operate concurrently with federal law. When an employer is subject
            to both federal and state statutes, the employer must comply with the stricter standard (e.g.,
            the longer 90-day notice window in New York or New Jersey, and federal filing rules).
          </p>
        </div>

        <div>
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">
            Which states require 90 days advance notice instead of 60 days?
          </h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            <strong>New York</strong>, <strong>New Jersey</strong>, and <strong>Maine</strong> require 90
            calendar days of advance notice before a covered plant closure or mass layoff takes effect,
            compared to the 60-day federal baseline.
          </p>
        </div>

        <div>
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">
            Which states require mandatory severance pay for laid-off workers?
          </h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            <strong>New Jersey</strong> mandates one week of severance pay per full year of employment,
            plus a 4-week penalty for notice failures. <strong>Maine</strong> mandates one week of severance
            pay per year of service for workers affected by covered facility closures or relocations.
          </p>
        </div>

        <div>
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">
            Do remote employees count toward state mini-WARN thresholds?
          </h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            Yes. Increasingly, state labor departments (including New York and New Jersey) consider remote
            workers who report to, receive assignments from, or are supervised from a state facility as
            part of that facility&apos;s headcount for WARN purposes.
          </p>
        </div>

        <div>
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">
            How can I monitor WARN filings in real-time?
          </h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            WARN Index monitors state labor agency publications daily across all 50 states and Washington
            DC. You can search our centralized <a href="/notices">layoff database</a>, filter by employer or
            industry, or download the full <a href="/api-docs">WARN dataset</a>.
          </p>
        </div>
      </div>
    </ContentPage>
  );
}
