import { Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { SearchBox } from "./SearchBox";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/notices", label: "Notices" },
  { to: "/companies", label: "Companies" },
  { to: "/states", label: "States" },
  { to: "/map", label: "Map" },
  { to: "/stats", label: "Stats" },
  { to: "/reports", label: "Reports" },
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
        className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
        activeProps={{ className: "bg-sky-50 text-sky-700" }}
      >
        Sign in
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-2 border-l border-slate-200 pl-3">
      <span className="hidden text-sm text-slate-600 sm:inline">{user.email}</span>
      {user.role !== "free" && (
        <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700">
          {user.role}
        </span>
      )}
      <button
        type="button"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
        className="rounded-md px-2 py-1.5 text-sm font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-700"
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
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3">
          <Link
            to="/"
            className="whitespace-nowrap text-lg font-semibold tracking-tight text-slate-900"
          >
            WARN <span className="text-sky-600">·</span>{" "}
            <span className="font-normal text-slate-500">Layoff notices</span>
          </Link>
          {/* Desktop nav + account (md and up). */}
          <div className="hidden items-center gap-3 md:flex">
            <nav className="flex gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
                  activeProps={{ className: "bg-sky-50 text-sky-700" }}
                  activeOptions={{ exact: item.to === "/" }}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <SearchBox />
            <AccountArea />
          </div>
          {/* Mobile hamburger (below md). */}
          <button
            type="button"
            className="rounded-md p-2 text-slate-700 hover:bg-slate-100 md:hidden"
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
          <div className="border-t border-slate-200 px-4 py-3 md:hidden">
            <div className="mb-3">
              <SearchBox />
            </div>
            <nav className="flex flex-col gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className="block rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                  activeProps={{ className: "bg-sky-50 text-sky-700" }}
                  activeOptions={{ exact: item.to === "/" }}
                  onClick={() => setMobileOpen(false)}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="mt-3 border-t border-slate-200 pt-3">
              <AccountArea />
            </div>
          </div>
        )}
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl space-y-2 px-4 py-4 text-xs text-slate-500">
          <nav className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Link className="hover:underline" to="/about">About</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/warn-act">What is the WARN Act?</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/methodology">Methodology</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/faq">FAQ</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/cited-by">Cited by</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/states">Browse states</Link>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/status">Scraper status</Link>
            <span aria-hidden>·</span>
            <a className="hover:underline" href="/feed.rss">RSS</a>
            <span aria-hidden>·</span>
            <Link className="hover:underline" to="/api-docs">Data &amp; API</Link>
          </nav>
          <p>Data from US state WARN Act listings · scraped daily.</p>
        </div>
      </footer>
    </div>
  );
}
