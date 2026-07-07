// Jurisdictions that will never go "Operational" by design — documented in
// docs/deferred-states.md. Shown with a neutral badge + tooltip on /status so
// a permanent no-source state doesn't read as a fresh outage. Keep in sync
// with that doc.
export const UNSUPPORTED: Record<string, string> = {
  AR: "WARN notices are confidential under Arkansas law (A.C.A. § 11-10-314); none are published.",
  NH: "New Hampshire does not publish WARN notices online; available only by records request.",
  WY: "WARN notices are confidential under Wyoming law (Wyo. Stat. § 9-2-2607); none are published.",
};

/**
 * States whose source publishes WARN notices but no employee-affected counts,
 * so layoff totals are structurally unavailable (not a scraping gap). Shown as
 * a note on the state detail page instead of a misleading zero.
 */
export const NO_COUNTS: Record<string, string> = {
  OK: "Oklahoma's WARN portal (Employ Oklahoma) publishes notice details but " +
    "not the number of employees affected, so worker counts are unavailable " +
    "for Oklahoma notices.",
};

/**
 * States where WARN notices are withheld by state statute (a legal barrier,
 * not a scraping gap). Their detail pages show an explainer instead of empty
 * stats — see UnavailableNotice.
 */
export interface LawBlockedInfo {
  statute: { cite: string; url: string };
  /** Agency the federal WARN notices are filed with. */
  agency: string;
  /** Why the data isn't public, in one or two sentences. */
  explanation: string;
  /** Official tools for residents to find their state legislators. */
  legislatorLinks: { label: string; url: string }[];
}

export const LAW_BLOCKED: Record<string, LawBlockedInfo> = {
  AR: {
    statute: {
      cite: "Ark. Code Ann. § 11-10-314",
      url: "https://law.justia.com/codes/arkansas/title-11/chapter-10/subchapter-3/section-11-10-314/",
    },
    agency: "Arkansas Division of Workforce Services",
    explanation:
      "Arkansas treats the information employers file with the Division of " +
      "Workforce Services as confidential, so the state does not publish WARN " +
      "notices or release them on request.",
    legislatorLinks: [
      {
        label: "Find your Arkansas legislators (District Finder)",
        url: "https://districtfinder.youraedi.com",
      },
      {
        label: "Arkansas General Assembly member directory",
        url: "https://arkleg.state.ar.us/Legislators/List",
      },
    ],
  },
  WY: {
    statute: {
      cite: "Wyo. Stat. § 9-2-2607",
      url: "https://law.justia.com/codes/wyoming/title-9/chapter-2/article-26/section-9-2-2607/",
    },
    agency: "Wyoming Department of Workforce Services",
    explanation:
      "Wyoming bars the Department of Workforce Services from disclosing " +
      "information in a way that reveals the identity of an employer, so the " +
      "state does not publish WARN notices.",
    legislatorLinks: [
      {
        label: "Wyoming Legislature member directory",
        url: "https://wyoleg.gov/Legislators",
      },
    ],
  },
};
