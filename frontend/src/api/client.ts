// Minimal typed fetch wrapper used by all TanStack Query hooks.
//
// The SPA and the API share the same origin in production (FastAPI mounts
// the built bundle via StaticFiles), so we use relative paths everywhere.
// In dev, vite.config.ts proxies these paths to the local FastAPI server.

import type {
  CompanyOut,
  EmployerStat,
  MonthStat,
  NoticeOut,
  Page,
  ScraperRunOut,
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

// ---------- Notices ----------

export interface NoticesQuery {
  state?: string;
  employer?: string;
  after?: string;
  before?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  listNotices: (q: NoticesQuery = {}) =>
    get<Page<NoticeOut>>("/notices" + qs(q as Record<string, string | number | undefined>)),
  getNotice: (id: string) =>
    get<NoticeOut>(`/notices/${encodeURIComponent(id)}`),

  // ---------- Companies ----------
  listCompanies: (q: {
    enriched?: boolean;
    sic_code?: string;
    limit?: number;
    offset?: number;
  } = {}) =>
    get<Page<CompanyOut>>(
      "/companies" +
        qs({
          enriched: q.enriched === undefined ? undefined : String(q.enriched),
          sic_code: q.sic_code,
          limit: q.limit,
          offset: q.offset,
        }),
    ),
  getCompany: (id: number) => get<CompanyOut>(`/companies/${id}`),
  listCompanyNotices: (id: number, q: { limit?: number; offset?: number } = {}) =>
    get<Page<NoticeOut>>(`/companies/${id}/notices` + qs(q)),

  // ---------- Scraper runs ----------
  listRuns: (q: { state?: string; status?: string; limit?: number; offset?: number } = {}) =>
    get<Page<ScraperRunOut>>("/scraper-runs" + qs(q)),

  // ---------- Stats ----------
  statsByState: (q: { after?: string; before?: string } = {}) =>
    get<StateStat[]>("/stats/by-state" + qs(q)),
  statsByMonth: (q: { state?: string; after?: string; before?: string } = {}) =>
    get<MonthStat[]>("/stats/by-month" + qs(q)),
  statsTopEmployers: (
    q: { limit?: number; state?: string; after?: string; before?: string } = {},
  ) => get<EmployerStat[]>("/stats/top-employers" + qs(q)),
};
