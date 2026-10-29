import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { Layout } from "./components/Layout";
import { NotFound } from "./components/NotFound";
import type { TimeRange } from "./components/TimeRangeToggle";
import { DEFAULT_SINCE, windowFor } from "./lib/timelapse";
import { NoticesPage } from "./routes/notices";
import { NoticeDetail } from "./routes/notice-detail";
import { RadarPage } from "./routes/radar";
import { CompaniesPage } from "./routes/companies";
import { CompanyDetail } from "./routes/company-detail";
import { StatesIndexPage } from "./routes/states-index";
import { ReportsPage } from "./routes/reports";
import { StatusPage } from "./routes/status";
import { AboutPage } from "./routes/content/about";
import { WarnActPage } from "./routes/content/warn-act";
import { MiniWarnLawsPage } from "./routes/content/mini-warn-laws";
import { MethodologyPage } from "./routes/content/methodology";
import { FaqPage } from "./routes/content/faq";
import { CitedByPage } from "./routes/content/cited-by";
import { ApiDocsPage } from "./routes/content/api-docs";
import { TermsPage } from "./routes/content/terms";
import { LoginPage } from "./routes/login";
import { SignupPage } from "./routes/signup";
import { AccountPage } from "./routes/account";
import { AlertsPage } from "./routes/alerts";

const rootRoute = createRootRoute({
  component: () => (
    <Layout>
      <Outlet />
    </Layout>
  ),
});

// The four chart/map-heavy pages are code-split: recharts (dashboard, stats,
// state-detail) and MapLibre (map, state-detail) each land in their own lazily
// fetched chunk instead of the entry bundle, so every first paint — and every
// visit that never opens them — skips those bytes entirely.
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: lazyRouteComponent(() => import("./routes/dashboard"), "Dashboard"),
});

// Shared by the list route and its detail route: detail URLs carry the list's
// search params through, so "← All notices/companies" links can restore the
// exact filters/sort/page the user left.
const validateNoticesSearch = (
  search: Record<string, unknown>,
): {
  state?: string;
  employer?: string;
  closure_category?: string;
  industry?: string;
  subsector?: string;
  min_layoffs?: number;
  after?: string;
  before?: string;
  page?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
} => ({
  state: (search.state as string) || undefined,
  employer: (search.employer as string) || undefined,
  closure_category: (search.closure_category as string) || undefined,
  industry: (search.industry as string) || undefined,
  subsector: (search.subsector as string) || undefined,
  min_layoffs: search.min_layoffs ? Number(search.min_layoffs) : undefined,
  after: (search.after as string) || undefined,
  before: (search.before as string) || undefined,
  page: search.page ? Number(search.page) : undefined,
  sort_by: (search.sort_by as string) || "notice_date",
  sort_dir: search.sort_dir === "asc" ? "asc" : "desc",
});

const validateCompaniesSearch = (
  search: Record<string, unknown>,
): {
  view?: "families";
  enriched?: "true" | "false" | undefined;
  unique_id?: "true";
  industry?: string;
  subsector?: string;
  page?: number;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
} => ({
  view: search.view === "families" ? "families" : undefined,
  enriched:
    search.enriched === "true" || search.enriched === "false"
      ? (search.enriched as "true" | "false")
      : undefined,
  unique_id: search.unique_id === "true" ? "true" : undefined,
  industry: (search.industry as string) || undefined,
  subsector: (search.subsector as string) || undefined,
  page: search.page ? Number(search.page) : undefined,
  sort_by: (search.sort_by as string) || "layoff_total",
  sort_dir: search.sort_dir === "asc" ? "asc" : "desc",
});

const noticesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/notices",
  validateSearch: validateNoticesSearch,
  component: NoticesPage,
});

const noticeDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/notices/$noticeId",
  validateSearch: validateNoticesSearch,
  component: NoticeDetail,
});

const radarRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/radar",
  validateSearch: (
    search: Record<string, unknown>,
  ): {
    state?: string;
    closure_category?: string;
    industry?: string;
    subsector?: string;
    min_layoffs?: number;
    days?: number;
    page?: number;
  } => ({
    state: (search.state as string) || undefined,
    closure_category: (search.closure_category as string) || undefined,
    industry: (search.industry as string) || undefined,
    subsector: (search.subsector as string) || undefined,
    // numParam (not Number()): junk like ?days=abc must become undefined, not
    // NaN — NaN survives ?? defaults and reaches the API as literal "NaN".
    min_layoffs: numParam(search.min_layoffs),
    days: numParam(search.days),
    page: numParam(search.page),
  }),
  component: RadarPage,
});

const companiesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/companies",
  validateSearch: validateCompaniesSearch,
  component: CompaniesPage,
});

const companyDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/companies/$companyId",
  validateSearch: validateCompaniesSearch,
  component: CompanyDetail,
});

// Strict numeric search-param parse: rejects "", booleans, and NaN — without
// this, ?lat=&lon= would parse to (0, 0) and center the map off West Africa.
const numParam = (v: unknown): number | undefined => {
  if (typeof v !== "number" && (typeof v !== "string" || v === "")) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
};

// Search ids that look numeric ("11" sectors, "2020" periods) arrive
// JSON-parsed as numbers; keep them strings so they compare equal to ours.
const strParam = (v: unknown): string | undefined =>
  v != null && v !== "" ? String(v) : undefined;

export type MapSearch = {
  state?: string;
  closure_category?: string;
  industry?: string;
  subsector?: string;
  min_layoffs?: number;
  after?: string;
  before?: string;
  lat?: number;
  lon?: number;
  zoom?: number;
  mode?: "heat";
  // Timeline. Quarterly since 2015 is the default and stays out of the URL.
  bucket?: "year" | "month";
  since?: number;
  /** The period on the map ("2020", "2020-Q2", "2020-04"), or "all" for
   *  every date. Absent: see MapPage. */
  at?: string;
};

const mapRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/map",
  validateSearch: (search: Record<string, unknown>): MapSearch => ({
    state: (search.state as string) || undefined,
    closure_category: (search.closure_category as string) || undefined,
    industry: strParam(search.industry),
    subsector: strParam(search.subsector),
    min_layoffs: numParam(search.min_layoffs),
    after: (search.after as string) || undefined,
    before: (search.before as string) || undefined,
    // Viewport — kept in the URL so back/refresh/share restore the same view.
    lat: numParam(search.lat),
    lon: numParam(search.lon),
    zoom: numParam(search.zoom),
    // Bubbles is the default and stays out of the URL.
    mode: search.mode === "heat" ? "heat" : undefined,
    bucket: search.bucket === "year" || search.bucket === "month" ? search.bucket : undefined,
    since: numParam(search.since),
    at: strParam(search.at),
  }),
  // Links from before the timeline used a one-year date filter for the old
  // year slider; that view is now the year's frame.
  beforeLoad: ({ search }) => {
    const y = search.after?.match(/^(\d{4})-01-01$/)?.[1];
    if (search.at || !y || search.before !== `${y}-12-31`) return;
    const since = windowFor(Number(y));
    throw redirect({
      to: "/map",
      search: {
        ...search,
        after: undefined,
        before: undefined,
        bucket: "year",
        since: since === DEFAULT_SINCE ? undefined : since,
        at: y,
      },
      replace: true,
    });
  },
  component: lazyRouteComponent(() => import("./routes/map"), "MapPage"),
});

// The time-lapse is /map's timeline now; old links land on the same view,
// as a heatmap like the page they came from.
const timelapseRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/timelapse",
  validateSearch: (
    search: Record<string, unknown>,
  ): { bucket?: "year" | "month"; since?: number; at?: string; industry?: string } => ({
    bucket: search.bucket === "year" || search.bucket === "month" ? search.bucket : undefined,
    since: numParam(search.since),
    at: strParam(search.at),
    industry: strParam(search.industry),
  }),
  beforeLoad: ({ search }) => {
    throw redirect({
      to: "/map",
      // `since` is always set: a /map URL with filters and neither a period
      // nor a window is an old all-time link (see MapPage).
      search: { ...search, since: search.since ?? DEFAULT_SINCE, mode: "heat" },
      replace: true,
    });
  },
});

const statsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/stats",
  validateSearch: (
    search: Record<string, unknown>,
  ): {
    state?: string;
    closure_category?: string;
    industry?: string;
    subsector?: string;
    after?: string;
    before?: string;
  } => ({
    state: (search.state as string) || undefined,
    closure_category: (search.closure_category as string) || undefined,
    industry: (search.industry as string) || undefined,
    subsector: (search.subsector as string) || undefined,
    after: (search.after as string) || undefined,
    before: (search.before as string) || undefined,
  }),
  component: lazyRouteComponent(() => import("./routes/stats"), "StatsPage"),
});

const statesIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/states",
  // Only non-default values reach the URL; the page fills in the defaults.
  validateSearch: (
    search: Record<string, unknown>,
  ): { range?: TimeRange; metric?: "notices"; sort?: "name" } => ({
    range: ["30d", "5y", "all"].includes(search.range as string)
      ? (search.range as TimeRange)
      : undefined,
    metric: search.metric === "notices" ? "notices" : undefined,
    sort: search.sort === "name" ? "name" : undefined,
  }),
  component: StatesIndexPage,
});

const stateDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/states/$state",
  component: lazyRouteComponent(() => import("./routes/state-detail"), "StateDetailPage"),
});

const reportsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reports",
  component: ReportsPage,
});

const outlookRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/outlook",
  component: lazyRouteComponent(() => import("./routes/outlook"), "OutlookPage"),
});

const industryReportRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reports/industry/$sector",
  // Code-split like the other chart/map-heavy pages: this route pulls in
  // recharts (trend chart) and MapLibre (sector map).
  component: lazyRouteComponent(() => import("./routes/industry-report"), "IndustryReportPage"),
});

const statusRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/status",
  component: StatusPage,
});

// Static content pages (Phase 3). Defined explicitly (not via a loop) so each
// path is a literal for TanStack's route-tree typing, matching the routes above.
const aboutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/about",
  component: AboutPage,
});
const warnActRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/warn-act",
  component: WarnActPage,
});
const miniWarnLawsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/mini-warn-laws",
  component: MiniWarnLawsPage,
});
const methodologyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/methodology",
  component: MethodologyPage,
});
const faqRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/faq",
  component: FaqPage,
});
const citedByRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/cited-by",
  component: CitedByPage,
});
const apiDocsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/api-docs",
  component: ApiDocsPage,
});

const termsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/terms",
  component: TermsPage,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});

const signupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/signup",
  component: SignupPage,
});

const alertsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/alerts",
  // `token` comes from the "Manage your alerts" link in every alert email.
  validateSearch: (search: Record<string, unknown>): { token?: string } => ({
    token: (search.token as string) || undefined,
  }),
  component: AlertsPage,
});

const accountRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/account",
  component: AccountPage,
});

const adminCompaniesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/companies",
  validateSearch: (search: Record<string, unknown>): { name?: string } => ({
    name: (search.name as string) || undefined,
  }),
  component: lazyRouteComponent(
    () => import("./routes/admin-companies"),
    "AdminCompaniesPage",
  ),
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  noticesRoute,
  noticeDetailRoute,
  radarRoute,
  companiesRoute,
  companyDetailRoute,
  mapRoute,
  timelapseRoute,
  statsRoute,
  statesIndexRoute,
  stateDetailRoute,
  reportsRoute,
  outlookRoute,
  industryReportRoute,
  statusRoute,
  aboutRoute,
  warnActRoute,
  miniWarnLawsRoute,
  methodologyRoute,
  faqRoute,
  citedByRoute,
  apiDocsRoute,
  termsRoute,
  loginRoute,
  signupRoute,
  accountRoute,
  alertsRoute,
  adminCompaniesRoute,
]);

export const router = createRouter({
  routeTree,
  scrollRestoration: true,
  defaultNotFoundComponent: NotFound,
});
