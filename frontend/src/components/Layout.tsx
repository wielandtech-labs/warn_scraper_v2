import { Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { SearchBox } from "./SearchBox";
import { ThemeToggle } from "./ThemeToggle";

/* The mark: three falling bars in brand red -- a layoff count stepping down.
   Inline so the header paints with no extra request; public/favicon.svg is
   the same drawing. */
function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="7" fill="#DA2F25" />
      <rect x="7" y="8" width="4.5" height="16" rx="1.5" fill="#fff" />
      <rect x="13.75" y="12" width="4.5" height="12" rx="1.5" fill="#fff" opacity="0.85" />
      <rect x="20.5" y="17" width="4.5" height="7" rx="1.5" fill="#fff" opacity="0.7" />
    </svg>
  );
}

const NAV_LINK =
  "relative flex h-14 items-center px-2 text-sm font-medium text-slate-600 transition-colors hover:text-slate-900 xl:px-3 dark:text-slate-400 dark:hover:text-slate-100";
// Active route: ink text + a brand-red rule under the label.
const NAV_ACTIVE =
  "!text-slate-900 dark:!text-slate-100 after:absolute after:inset-x-2 xl:after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full after:bg-brand";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/notices", label: "Notices" },
  { to: "/companies", label: "Companies" },
  { to: "/states", label: "States" },
  { to: "/map", label: "Map" },
  { to: "/stats", label: "Trends" },
  { to: "/reports", label: "Reports" },
  { to: "/outlook", label: "Outlook" },
];

function AccountArea() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      // Cached payloads are role-shaped; drop everything on sign-out.
      await queryClient.invalidateQueries();
    },
  });

  if (auth.isLoading) return null;
  const user = auth.data;
  if (!user) {
    return (
      <Link
        to="/login"
        className="whitespace-nowrap rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        activeProps={{ className: "bg-sky-50 text-sky-700 dark:bg-sky-950 dark:text-sky-300" }}
      >
        Sign in
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-2 border-l border-slate-200 pl-3 dark:border-slate-800">
      <Link
        to="/account"
        className="hidden text-sm text-slate-600 hover:underline sm:inline dark:text-slate-400"
      >
        {user.email}
      </Link>
      <Link to="/account" className="text-sm text-slate-600 sm:hidden dark:text-slate-400">
        Account
      </Link>
      {user.role === "admin" && (
        <Link
          to="/admin/companies"
          className="text-sm text-slate-600 hover:underline dark:text-slate-400"
        >
          Admin
        </Link>
      )}
      {user.role !== "free" && (
        <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700 dark:bg-sky-900 dark:text-sky-300">
          {user.role}
        </span>
      )}
      <button
        type="button"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
        className="rounded-md px-2 py-1.5 text-sm font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-300"
      >
        Sign out
      </button>
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-[1100] border-b border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-3 px-4">
          <Link
            to="/"
            className="flex items-center gap-2.5 whitespace-nowrap text-slate-900 dark:text-slate-100"
          >
            <BrandMark className="h-7 w-7" />
            <span className="font-display text-xl font-semibold tracking-tight">WARN Index</span>
            <span className="hidden border-l border-slate-300 pl-2.5 text-xs font-medium uppercase tracking-[0.12em] text-slate-500 2xl:inline dark:border-slate-700 dark:text-slate-400">
              Layoff notices
            </span>
          </Link>
          {/* Desktop nav + account (lg and up; below that it does not fit). */}
          <div className="hidden items-center gap-3 lg:flex">
            <nav className="flex">
              {NAV.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className={NAV_LINK}
                  activeProps={{ className: NAV_ACTIVE }}
                  activeOptions={{ exact: item.to === "/" }}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <SearchBox />
            <ThemeToggle />
            <AccountArea />
          </div>
          {/* Mobile hamburger (below md). */}
          <button
            type="button"
            className="rounded-md p-2 text-slate-700 hover:bg-slate-100 lg:hidden dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label="Menu"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((v) => !v)}
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              {mobileOpen ? (
                <>
                  <line x1="6" y1="6" x2="18" y2="18" />
                  <line x1="6" y1="18" x2="18" y2="6" />
                </>
              ) : (
                <>
                  <line x1="3" y1="6" x2="21" y2="6" />
                  <line x1="3" y1="12" x2="21" y2="12" />
                  <line x1="3" y1="18" x2="21" y2="18" />
                </>
              )}
            </svg>
          </button>
        </div>
        {/* Mobile dropdown panel. */}
        {mobileOpen && (
          <div className="border-t border-slate-200 px-4 py-3 lg:hidden dark:border-slate-800">
            <div className="mb-3">
              <SearchBox />
            </div>
            <nav className="flex flex-col gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className="block border-l-2 border-transparent px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
                  activeProps={{ className: "!border-brand !text-slate-900 dark:!text-slate-100" }}
                  activeOptions={{ exact: item.to === "/" }}
                  onClick={() => setMobileOpen(false)}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="mt-3 flex items-center justify-between border-t border-slate-200 pt-3 dark:border-slate-800">
              <AccountArea />
              <ThemeToggle />
            </div>
          </div>
        )}
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
      <footer className="mt-10 border-t border-slate-200 dark:border-slate-800">
        <div className="mx-auto max-w-7xl space-y-3 px-4 py-8 text-xs text-slate-500 dark:text-slate-400">
          <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
            <BrandMark className="h-5 w-5" />
            <span className="font-display text-base font-semibold">WARN Index</span>
          </div>
          <nav className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Link className="hover:underline" to="/about">About</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/warn-act">What is the WARN Act?</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/mini-warn-laws">State Mini-WARN Laws</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/methodology">Methodology</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/faq">FAQ</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/cited-by">Press &amp; Cited By</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/states">Browse states</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/status">Scraper status</Link>
            <span aria-hidden>·</span>
            <a className="hover:underline" href="/feed.rss">RSS</a>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/api-docs">Data &amp; API</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/terms">Terms</Link>
          </nav>
          <p>
            The national WARN layoff tracker and database — daily Worker Adjustment and Retraining Notification filings from all 50 states.
          </p>
        </div>
      </footer>
    </div>
  );
}
