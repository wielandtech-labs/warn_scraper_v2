// Hand-written TypeScript mirrors of warn_v2/api/schemas.py and stats.py.
// Keep in sync when the API schema changes. (A follow-up will wire
// openapi-typescript codegen into CI to make drift impossible.)

export interface LocationOut {
  id: number;
  city: string | null;
  county: string | null;
  state: string;
  zip: string | null;
  lat: number | null;
  lon: number | null;
}

export interface CompanyOut {
  id: number;
  name: string;
  sic_code: string | null;
  sic_desc: string | null;
  naics_code: string | null;
  naics_desc: string | null;
  website: string | null;
  enriched_at: string | null;
  enrichment_confidence: number | null;
  enrichment_source: "provider" | "edgar" | "claude" | null;
  // Workers affected (rolled up over merged dupes, superseded excluded).
  // Computed only by the companies list endpoint; null elsewhere.
  layoff_total?: number | null;
  // D&B enrichment fields — present only for paid sessions and above; the API
  // omits the keys entirely for anonymous/free viewers. Raw DUNS identifiers
  // are enterprise/admin only.
  duns?: string | null;
  parent_duns?: string | null;
  parent_company_name?: string | null;
  global_ultimate_name?: string | null;
  hq_address?: string | null;
  employee_count?: number | null;
}

export interface AuthUser {
  email: string;
  role: "admin" | "enterprise" | "paid" | "free";
}

export interface ApiKeyOut {
  id: number;
  prefix: string;
  name: string | null;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** POST /api/keys response — `key` is the raw value, shown exactly once. */
export interface ApiKeyCreatedOut extends ApiKeyOut {
  key: string;
}

export interface KeyUsageOut {
  prefix: string;
  name: string | null;
  today: number;
}

export interface UsageOut {
  tier: string;
  per_minute_limit: number | null;
  daily_limit: number | null;
  today: number;
  keys: KeyUsageOut[];
}

export interface NoticeOut {
  notice_id: string;
  state: string;
  employer: string;
  notice_date: string | null;
  effective_date: string | null;
  layoff_count: number | null;
  closure_type: string | null;
  closure_category: string | null;
  address: string | null;
  source_url: string | null;
  raw_notice_url: string | null;
  pdf_path: string | null;
  scraped_at: string;
  company: CompanyOut | null;
  location: LocationOut | null;
}

// One occupation in a layoff cohort. Two sources (see the parent's
// source/occupation_source field): "employer_filing" rows are actual job
// titles + counts parsed from the WARN letter's positions table;
// "oews_estimate" rows apply the national OEWS staffing pattern to the
// notice's layoff count — a statistical prior, not data about the actual
// affected roles.
export interface OccupationEstimate {
  soc_code: string | null; // null for employer_filing rows (free-text titles)
  title: string;
  pct: number; // share of industry employment (OEWS) or of the filing's total
  estimate: number | null; // workers; exact for employer_filing rows
}

export type OccupationSource = "employer_filing" | "oews_estimate";

// /radar — an upcoming layoff cohort (effective_date is today or later).
export interface RadarNoticeOut {
  notice_id: string;
  employer: string;
  company_id: number | null;
  state: string;
  city: string | null;
  county: string | null;
  notice_date: string | null;
  effective_date: string;
  days_until: number;
  layoff_count: number | null;
  closure_category: string | null;
  naics_code: string | null; // null → "industry unknown"
  sector: string | null;
  sector_name: string | null;
  occupation_preview: OccupationEstimate[] | null; // top 3; null without data
  occupation_source: OccupationSource | null; // null when no preview
  oews_vintage: string | null;
}

// /notices/{id}/occupation-mix — the full occupation mix (filed or estimated).
export interface OccupationMixOut {
  notice_id: string;
  available: boolean;
  reason: "no_naics" | "no_pattern" | null;
  source: OccupationSource | null; // null when unavailable
  naics_code: string | null;
  matched_naics: string | null;
  match_level: "4-digit" | "3-digit" | "sector" | null;
  industry_title: string | null;
  coverage_pct: number | null;
  layoff_count: number | null;
  oews_vintage: string | null;
  occupations: OccupationEstimate[];
}

export interface ScraperRunOut {
  id: number;
  state: string;
  started_at: string;
  finished_at: string | null;
  rows_scraped: number | null;
  rows_new: number | null;
  status: string;
  error: string | null;
}

// /scraper-runs/status — per-state scraper health for the status page.
export interface StateStatusOut {
  state: string;
  last_run_at: string;
  last_status: string;
  last_finished_at: string | null;
  rows_scraped: number | null;
  rows_new: number | null;
  error: string | null;
  last_success_at: string | null;
  first_notice_date: string | null;
  last_notice_date: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// /search responses
export interface SearchCompanyOut {
  id: number;
  name: string;
}

export interface SearchNoticeOut {
  notice_id: string;
  employer: string;
  state: string;
  notice_date: string | null;
}

export interface SearchResults {
  companies: SearchCompanyOut[];
  notices: SearchNoticeOut[];
}

// /stats responses
export interface StateStat {
  state: string;
  notice_count: number;
  layoff_total: number;
}

export interface MonthStat {
  month: string; // "YYYY-MM"
  notice_count: number;
  layoff_total: number;
  // Pace projection for the current, incomplete month; set only on the final
  // row when it is the current month, null on complete periods.
  projected_notice_count?: number | null;
  projected_layoff_total?: number | null;
}

export interface PeriodStat {
  period: string; // "YYYY-MM-DD" for day buckets, "YYYY-MM" for month buckets
  notice_count: number;
  layoff_total: number;
  // Pace projection for the current, incomplete month/year; set only on the
  // final row when it is the current period, always null for day buckets.
  projected_notice_count?: number | null;
  projected_layoff_total?: number | null;
}

export interface EmployerStat {
  employer: string;
  company_id: number | null;
  notice_count: number;
  layoff_total: number;
}

// One county ranked by layoffs as a share of its employment base (Census CBP).
export interface CountyImpactStat {
  state: string;
  county: string; // display name, legal-type suffix stripped ("Sedgwick")
  notice_count: number;
  layoff_total: number;
  employment_base: number;
  impact_pct: number; // layoff_total / employment_base * 100
  cbp_year: number | null;
}

// A member of a corporate family (siblings sharing a parent). Anonymous by
// design — identified only by the member WARN company, never the D&B parent name.
export interface FamilyMemberOut {
  company_id: number;
  name: string;
  notice_count: number;
  layoff_total: number;
  is_self: boolean;
}

export interface ParentGroupStat {
  representative_company_id: number;
  representative_company_name: string;
  member_count: number;
  notice_count: number;
  layoff_total: number;
}

export interface SubsectorStat {
  code: string; // 3-digit NAICS subsector, e.g. "311"
  name: string;
  notice_count: number;
  layoff_total: number;
}

export interface IndustryStat {
  sector: string; // NAICS sector id, e.g. "31-33"
  name: string;
  notice_count: number;
  layoff_total: number;
  subsectors: SubsectorStat[];
}

// /reports/industries — per-NAICS-sector scorecard summary, worst score first.
export interface IndustryScorecard {
  sector: string; // NAICS sector id, e.g. "31-33"
  sector_name: string;
  score: number | null; // 0-100, higher = healthier; null below the data threshold
  grade: string; // "A".."F" or "N/A"
  cur_layoffs: number;
  prior_layoffs: number;
  cur_notices: number;
  delta_pct: number | null;
  generated_at: string;
}
