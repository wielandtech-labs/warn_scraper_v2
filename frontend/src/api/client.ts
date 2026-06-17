// Minimal typed fetch wrapper used by all TanStack Query hooks.
//
// The SPA and the API share the same origin in production (FastAPI mounts
// the built bundle via StaticFiles), so we use relative paths everywhere.
// In dev, vite.config.ts proxies these paths to the local FastAPI server.

import type {
  AuthUser,
  CompanyOut,
  EmployerStat,
  FamilyMemberOut,
  IndustryStat,
  MonthStat,
  NoticeOut,
  Page,
  ParentGroupStat,
  ScraperRunOut,
  SearchResults,
  StateStat,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const filtered = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== "",
  );
  if (filtered.length === 0) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of filtered) sp.set(k, String(v));
  return "?" + sp.toString();
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path, { headers: { Accept: "application/json" } });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new ApiError(resp.status, text || resp.statusText);
  }
  return (await resp.json()) as T;
}

// Same-origin fetch sends the session cookie by default; no credentials flag needed.
async function post<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new ApiError(resp.status, text || resp.statusText);
  }
  return (await resp.json()) as T;
}

// ---------- Notices ----------

export interface NoticesQuery {
  state?: string;
  employer?: string;
  closure_category?: string;
  industry?: string;
  subsector?: string;
  after?: string;
  before?: string;
  geocoded_only?: boolean;
  sort_by?: string;
  sort_dir?: string;
  limit?: number;
  offset?: number;
}

/** Lightweight pin object returned by /api/map-pins. */
export interface MapPin {
  notice_id: string;
  employer: string;
  state: string;
  notice_date: string | null;
  layoff_count: number | null;
  lat: number;
  lon: number;
}

export interface MapPinQuery {
  state?: string;
  closure_category?: string;
  industry?: string;
  subsector?: string;
  after?: string;
  before?: string;
  // Viewport bounds — sent together so the API returns only visible pins.
  min_lat?: number;
  min_lon?: number;
  max_lat?: number;
  max_lon?: number;
  // Ceiling on pins returned (API caps at 50 000). The map sets a smaller,
  // device-dependent cap so phones don't instantiate tens of thousands of markers.
  limit?: number;
}

export const api = {
  // ---------- Auth ----------
  login: (email: string, password: string) =>
    post<AuthUser>("/api/auth/login", { email, password }),
  logout: () => post<{ status: string }>("/api/auth/logout"),
  me: () => get<AuthUser>("/api/auth/me"),

  listNotices: (q: NoticesQuery = {}) =>
    get<Page<NoticeOut>>("/api/notices" + qs(q as Record<string, string | number | undefined>)),
  getNotice: (id: string) =>
    get<NoticeOut>(`/api/notices/${encodeURIComponent(id)}`),

  /** Geocoded notices for the map — lightweight DTO, viewport-scoped, up to 50 000 per fetch. */
  listMapPins: (q: MapPinQuery = {}) =>
    get<MapPin[]>("/api/map-pins" + qs(q as Record<string, string | number | undefined>)),

  // ---------- Companies ----------
  listCompanies: (q: {
    enriched?: boolean;
    has_duns?: boolean;
    sic_code?: string;
    industry?: string;
    subsector?: string;
    sort_by?: string;
    sort_dir?: string;
    limit?: number;
    offset?: number;
  } = {}) =>
    get<Page<CompanyOut>>(
      "/api/companies" +
        qs({
          enriched: q.enriched === undefined ? undefined : String(q.enriched),
          has_duns: q.has_duns === undefined ? undefined : String(q.has_duns),
          sic_code: q.sic_code,
          industry: q.industry,
          subsector: q.subsector,
          sort_by: q.sort_by,
          sort_dir: q.sort_dir,
          limit: q.limit,
          offset: q.offset,
        }),
    ),
  getCompany: (id: number) => get<CompanyOut>(`/api/companies/${id}`),
  listCompanyNotices: (id: number, q: { limit?: number; offset?: number } = {}) =>
    get<Page<NoticeOut>>(`/api/companies/${id}/notices` + qs(q)),
  /** Sibling companies sharing this company's corporate family (empty if none). */
  getCompanyFamily: (id: number) =>
    get<FamilyMemberOut[]>(`/api/companies/${id}/family`),

  // ---------- Scraper runs ----------
  listRuns: (q: { state?: string; status?: string; limit?: number; offset?: number } = {}) =>
    get<Page<ScraperRunOut>>("/api/scraper-runs" + qs(q)),

  // ---------- Stats ----------
  statsByState: (
    q: {
      closure_category?: string;
      industry?: string;
      subsector?: string;
      after?: string;
      before?: string;
    } = {},
  ) => get<StateStat[]>("/api/stats/by-state" + qs(q)),
  statsByMonth: (
    q: {
      state?: string;
      closure_category?: string;
      industry?: string;
      subsector?: string;
      after?: string;
      before?: string;
    } = {},
  ) => get<MonthStat[]>("/api/stats/by-month" + qs(q)),
  statsTopEmployers: (
    q: {
      limit?: number;
      state?: string;
      closure_category?: string;
      industry?: string;
      subsector?: string;
      after?: string;
      before?: string;
    } = {},
  ) => get<EmployerStat[]>("/api/stats/top-employers" + qs(q)),
  statsByParentGroup: (
    q: { limit?: number; state?: string; after?: string; before?: string } = {},
  ) => get<ParentGroupStat[]>("/api/stats/by-parent-group" + qs(q)),
  statsIndustries: () => get<IndustryStat[]>("/api/stats/industries"),

  // ---------- Search ----------
  search: (q: string, limit = 8) =>
    get<SearchResults>("/api/search" + qs({ q, limit })),
};
