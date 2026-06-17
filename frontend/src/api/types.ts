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
  website: string | null;
  enriched_at: string | null;
  enrichment_confidence: number | null;
  enrichment_source: "provider" | "edgar" | "claude" | null;
  // Workers affected (rolled up over merged dupes, superseded excluded).
  // Computed only by the companies list endpoint; null elsewhere.
  layoff_total?: number | null;
  // D&B enrichment fields — present only for paid/admin sessions; the API
  // omits the keys entirely for anonymous/free viewers.
  duns?: string | null;
  parent_duns?: string | null;
  parent_company_name?: string | null;
  global_ultimate_name?: string | null;
  hq_address?: string | null;
  employee_count?: number | null;
}

export interface AuthUser {
  email: string;
  role: "admin" | "paid" | "free";
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
}

export interface EmployerStat {
  employer: string;
  company_id: number | null;
  notice_count: number;
  layoff_total: number;
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
}

export interface IndustryStat {
  sector: string; // NAICS sector id, e.g. "31-33"
  name: string;
  notice_count: number;
  subsectors: SubsectorStat[];
}
