/* State "mini-WARN" laws: the data behind the /mini-warn-laws guide and the
   "WARN rules" card on each state page, kept in one place so the two can't
   disagree. Plain-language summaries, not legal advice. */

export interface StateRule {
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
  /** One-paragraph summary for the guide's "Other States" cards; set on the
   *  states that have no hand-written profile section there. */
  summary?: string;
}

export const STATE_RULES: StateRule[] = [
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
  {
    state: "Washington",
    code: "WA",
    statute: "Securing Timely Notification and Benefits for Laid-Off Employees Act",
    statuteCitation: "Wash. Rev. Code ch. 49.45",
    employerSize: "50+ employees in Washington (excluding part-time)",
    noticePeriod: "60 calendar days",
    closureTrigger: "Shutdown of a single site causing job losses for 50+ employees",
    layoffTrigger: "50+ employees in any 30-day period, with no single-site limit",
    severanceRequirement: "None mandated (back pay and benefits for up to 60 days if notice is late)",
    keyDifferences: [
      "50-employee threshold (vs. 100 federal)",
      "Mass layoff: 50 job losses in 30 days, with no single-site limit and no 33% test",
      "Notice to the Employment Security Department and affected employees (or their union)",
      "Civil penalty up to $500 per day, plus back pay and benefits for up to 60 days",
      "In effect since July 27, 2025",
    ],
    summary:
      "Since July 2025, employers with 50+ employees in Washington must give 60 days notice " +
      "of a site closing or a mass layoff of 50+ employees in 30 days.",
  },
  {
    state: "Nebraska",
    code: "NE",
    statute: "Nebraska Worker Adjustment and Retraining Notification Act",
    statuteCitation: "Neb. Rev. Stat. §§ 48-4001 to 48-4006",
    employerSize: "100+ employees (excluding part-time)",
    noticePeriod: "90 calendar days",
    closureTrigger: "Shutdown of a single site causing job losses for 100+ employees",
    layoffTrigger: "100+ employees at a single site in any 30-day period",
    severanceRequirement: "None mandated (civil penalty up to $100 per day)",
    keyDifferences: [
      "90 days notice (vs. 60 days federal)",
      "Higher site thresholds than federal: 100 job losses for a closing or mass layoff (vs. 50)",
      "Notice to affected employees (or their union) and the Nebraska Department of Labor",
      "A civil penalty of up to $100 per day is the only remedy",
      "In effect since July 18, 2026",
    ],
    summary:
      "Since July 2026, employers with 100+ employees must give 90 days notice of a site " +
      "closing or mass layoff affecting 100+ employees.",
  },
  {
    state: "Vermont",
    code: "VT",
    statute: "Vermont Notice of Potential Layoffs Act",
    statuteCitation: "21 V.S.A. §§ 411–418",
    employerSize: "50+ employees (full-time, or part-time working 1,040+ hours a year)",
    noticePeriod: "45 days to the state; 30 days to employees",
    closureTrigger: "Permanent shutdown, or a stoppage affecting 50+ employees over 90 days",
    layoffTrigger: "50+ permanent job losses across Vermont worksites in any 90-day period",
    severanceRequirement: "Up to 10 days of severance pay plus a month of health coverage if notice is late",
    keyDifferences: [
      "50-employee threshold (vs. 100 federal)",
      "45 days notice to the state Commerce and Labor departments; 30 days to employees, their union, and local officials",
      "Job losses at all Vermont worksites count toward a mass layoff, over 90 days",
      "Administrative penalty of $500 per day of missing notice",
    ],
    summary:
      "Employers with 50+ employees must notify the state 45 days, and employees 30 days, " +
      "before a closing or a layoff of 50+ employees within 90 days.",
  },
  {
    state: "New Hampshire",
    code: "NH",
    statute: "New Hampshire WARN law",
    statuteCitation: "N.H. Rev. Stat. Ann. ch. 275-F",
    employerSize: "100+ employees in New Hampshire (excluding part-time)",
    noticePeriod: "60 calendar days",
    closureTrigger: "50+ employees at a single site in any 30-day period",
    layoffTrigger: "250+ employees, or 25–249 if 33%+ of the workforce, at one site in 30 days",
    severanceRequirement: "None mandated (back pay and benefits for up to 60 days if notice is late)",
    keyDifferences: [
      "Lower mass layoff threshold: 250 employees (vs. 500 federal), or 25 if a third of the workforce (vs. 50)",
      "Notice also goes to the labor commissioner, the attorney general, and local officials",
      "Civil penalty up to $2,500 plus $100 per employee per day",
    ],
    summary:
      "Employers with 100+ employees must give 60 days notice, with a lower mass layoff " +
      "threshold than federal WARN: 250 employees, or 25 if they are a third of the workforce.",
  },
  {
    state: "Iowa",
    code: "IA",
    statute: "Iowa Worker Adjustment and Retraining Notification Act",
    statuteCitation: "Iowa Code ch. 84C",
    employerSize: "25+ employees (excluding part-time)",
    noticePeriod: "30 calendar days",
    closureTrigger: "Shutdown of a single site causing job losses for 25+ employees",
    layoffTrigger: "25+ employees at a single site in any 30-day period",
    severanceRequirement: "None mandated by statute",
    keyDifferences: [
      "25-employee threshold, the lowest of the state laws here (vs. 100 federal)",
      "Shorter notice: 30 days. Employers also covered by federal WARN still owe its 60 days",
      "Notice to affected employees (or their union) and Iowa Workforce Development",
    ],
    summary:
      "Reaches small employers: 25+ employees must give 30 days notice of a site closing or " +
      "a layoff of 25+ employees within 30 days.",
  },
  {
    state: "Ohio",
    code: "OH",
    statute: "Ohio mini-WARN law",
    statuteCitation: "Ohio Rev. Code § 4113.31",
    employerSize: "100+ employees (working 4,000+ hours a week in total)",
    noticePeriod: "60 calendar days",
    closureTrigger: "Same as federal: 50+ employees at a single site",
    layoffTrigger: "50+ employees at a single site in any 30-day period, with no 33% test",
    severanceRequirement: "None mandated (federal WARN remedies apply)",
    keyDifferences: [
      "Mass layoff: 50 job losses at one site in 30 days, with no 33% test (federal: 50–499 must be a third of the site)",
      "Notice also goes to the Director of Job and Family Services and to the municipal and county chief elected officials",
      "Employees can seek the federal WARN remedies of back pay and benefits",
      "In effect since September 30, 2025",
    ],
    summary:
      "Since September 2025, employers with 100+ employees must give 60 days notice of a " +
      "mass layoff of 50+ at one site, without the federal 33% test.",
  },
  {
    state: "Delaware",
    code: "DE",
    statute: "Delaware Worker Adjustment and Retraining Notification Act",
    statuteCitation: "19 Del. C. ch. 19",
    employerSize: "100+ employees (excluding part-time)",
    noticePeriod: "60 calendar days",
    closureTrigger: "50+ employees at a single site in any 30-day period",
    layoffTrigger: "500+ employees, or 50–499 if 33%+ of the site, in any 30-day period",
    severanceRequirement: "None mandated (back pay and benefits for up to 60 days if notice is late)",
    keyDifferences: [
      "Also covers relocating operations 50+ miles away",
      "Notice to the Division of Employment and Training and the local Workforce Development Board, with each worker's contact details",
      "Notice must describe severance, payouts, and relocation options",
      "Civil penalty of $1,000 per day, or $100 per day per worker if greater",
    ],
    summary:
      "Employers with 100+ employees must give 60 days notice of closings, mass layoffs, and " +
      "relocations of 50+ miles, including each worker's contact details for the state.",
  },
];

/** States the guide mentions only briefly, under "Other States". */
export const OTHER_STATE_NOTES: { code: string; title: string; note: string }[] = [
  {
    code: "CT",
    title: "Connecticut (Conn. Gen. Stat. § 31-51o)",
    note:
      "Requires employers with 100+ workers closing or relocating an establishment to pay for " +
      "continued group health insurance coverage for affected employees for up to 120 days. " +
      "From October 1, 2026, a WARN notice filed with the state Labor Department must also say " +
      "whether the layoffs relate to artificial intelligence or other technological change " +
      "(Public Act 26-15).",
  },
  {
    code: "MD",
    title: "Maryland (Labor & Empl. § 11-301)",
    note:
      "Mandatory 60 days notice for employers with 50+ employees reducing operations by at least " +
      "25% or 15 employees (whichever is greater).",
  },
  {
    code: "MA",
    title: "Massachusetts (M.G.L. c. 151A §§ 71A–71H)",
    note:
      "Advance notice of a plant closing is voluntary. The law instead provides reemployment " +
      "assistance and health insurance benefits for workers laid off from facilities with 50+ employees.",
  },
  {
    code: "MI",
    title: "Michigan (MCL 450.736)",
    note:
      "No mandatory state law. The state encourages employers considering a closing or " +
      "relocation to give notice as early as possible.",
  },
  {
    code: "MN",
    title: "Minnesota (Minn. Stat. § 116L.976)",
    note:
      "Advance notice is voluntary, but an employer that gives notice, including federal WARN " +
      "notice, must report the names, addresses, and occupations of affected employees to the state.",
  },
  {
    code: "TN",
    title: "Tennessee (Tenn. Code § 50-1-601)",
    note:
      "Covers employers with 50–99 employees who are not covered under federal WARN, requiring " +
      "notification to the state labor department.",
  },
];

/** States with no mini-WARN law of their own, where federal WARN alone sets the
 *  rules, with any smaller related rule worth a line. Checked 2026-10-31 against
 *  state agency pages or statutes, J.J. Keller's per-state compliance summaries
 *  ("has no statutes regarding plant closings or mass layoffs"), and 2026
 *  surveys of state laws, none of which list these states. */
export const NO_STATE_LAW: Record<string, string | null> = {
  AL: "Employers must tell the nearest unemployment claims office about a mass separation (Ala. Admin. Code r. 480-4-3.10).",
  AK: null,
  AZ: null,
  AR: null,
  CO: null,
  DC: "The Department of Employment Services encourages voluntary notice of layoffs that federal WARN doesn't cover.",
  FL: null,
  GA: null,
  ID: null,
  IN: null,
  KS: null,
  KY: null,
  LA: null,
  MS: null,
  MO: null,
  MT: "Montana's plant-closing statute covers only state government operations (Mont. Code Ann. §§ 39-2-1001 to -1004).",
  NV: null,
  NM: null,
  NC: null,
  ND: null,
  OK: null,
  OR: "Federal WARN notices go to Oregon's Higher Education Coordinating Commission (ORS 285A.516).",
  PA: null,
  RI: null,
  SC: "South Carolina repealed its old shutdown-notice rule in 2010.",
  SD: null,
  TX: null,
  UT: null,
  VA: null,
  WV: null,
  WY: null,
};

// Profiles with their own section in the guide; the rest live under "Other States".
const GUIDE_ANCHOR: Record<string, string> = {
  CA: "california",
  NY: "new-york",
  NJ: "new-jersey",
  IL: "illinois",
};

/** Where a state's rules sit in the /mini-warn-laws guide. */
export const guideAnchor = (code: string) => GUIDE_ANCHOR[code] ?? "other-states";
