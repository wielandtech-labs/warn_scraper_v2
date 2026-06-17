import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";

import { Layout } from "./components/Layout";
import { Dashboard } from "./routes/dashboard";
import { NoticesPage } from "./routes/notices";
import { NoticeDetail } from "./routes/notice-detail";
import { CompaniesPage } from "./routes/companies";
import { CompanyDetail } from "./routes/company-detail";
import { MapPage } from "./routes/map";
import { StatsPage } from "./routes/stats";
import { StatesIndexPage } from "./routes/states-index";
import { StateDetailPage } from "./routes/state-detail";
import { AboutPage } from "./routes/content/about";
import { WarnActPage } from "./routes/content/warn-act";
import { MethodologyPage } from "./routes/content/methodology";
import { FaqPage } from "./routes/content/faq";
import { CitedByPage } from "./routes/content/cited-by";
import { ApiDocsPage } from "./routes/content/api-docs";
import { LoginPage } from "./routes/login";

const rootRoute = createRootRoute({
  component: () => (
    <Layout>
      <Outlet />
    </Layout>
  ),
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: Dashboard,
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
  duns?: "true";
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
  duns: search.duns === "true" ? "true" : undefined,
  industry: (search.industry as string) || undefined,
  subsector: (search.subsector as string) || undefined,
  page: search.page ? Number(search.page) : undefined,
  sort_by: (search.sort_by as string) || "name",
  sort_dir: search.sort_dir === "desc" ? "desc" : "asc",
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

const mapRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/map",
  validateSearch: (
    search: Record<string, unknown>,
  ): {
    state?: string;
    closure_category?: string;
    industry?: string;
    subsector?: string;
    after?: string;
    before?: string;
    lat?: number;
    lon?: number;
    zoom?: number;
  } => ({
    state: (search.state as string) || undefined,
    closure_category: (search.closure_category as string) || undefined,
    industry: (search.industry as string) || undefined,
    subsector: (search.subsector as string) || undefined,
    after: (search.after as string) || undefined,
    before: (search.before as string) || undefined,
    // Viewport — kept in the URL so back/refresh/share restore the same view.
    lat: numParam(search.lat),
    lon: numParam(search.lon),
    zoom: numParam(search.zoom),
  }),
  component: MapPage,
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
  component: StatsPage,
});

const statesIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/states",
  component: StatesIndexPage,
});

const stateDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/states/$state",
  component: StateDetailPage,
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

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  noticesRoute,
  noticeDetailRoute,
  companiesRoute,
  companyDetailRoute,
  mapRoute,
  statsRoute,
  statesIndexRoute,
  stateDetailRoute,
  aboutRoute,
  warnActRoute,
  methodologyRoute,
  faqRoute,
  citedByRoute,
  apiDocsRoute,
  loginRoute,
]);

export const router = createRouter({ routeTree, scrollRestoration: true });
