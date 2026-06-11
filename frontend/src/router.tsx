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

const noticesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/notices",
  validateSearch: (
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
  }),
  component: NoticesPage,
});

const noticeDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/notices/$noticeId",
  component: NoticeDetail,
});

const companiesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/companies",
  validateSearch: (
    search: Record<string, unknown>,
  ): {
    view?: "families";
    enriched?: "true" | "false" | undefined;
    industry?: string;
    subsector?: string;
    page?: number;
  } => ({
    view: search.view === "families" ? "families" : undefined,
    enriched:
      search.enriched === "true" || search.enriched === "false"
        ? (search.enriched as "true" | "false")
        : undefined,
    industry: (search.industry as string) || undefined,
    subsector: (search.subsector as string) || undefined,
    page: search.page ? Number(search.page) : undefined,
  }),
  component: CompaniesPage,
});

const companyDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/companies/$companyId",
  component: CompanyDetail,
});

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
  } => ({
    state: (search.state as string) || undefined,
    closure_category: (search.closure_category as string) || undefined,
    industry: (search.industry as string) || undefined,
    subsector: (search.subsector as string) || undefined,
    after: (search.after as string) || undefined,
    before: (search.before as string) || undefined,
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
  loginRoute,
]);

export const router = createRouter({ routeTree });
