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
