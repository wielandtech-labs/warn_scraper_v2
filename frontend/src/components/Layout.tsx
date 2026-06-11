import { Link } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/notices", label: "Notices" },
  { to: "/companies", label: "Companies" },
  { to: "/map", label: "Map" },
  { to: "/stats", label: "Stats" },
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
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-semibold tracking-tight text-slate-900">
            WARN <span className="text-sky-600">·</span>{" "}
            <span className="font-normal text-slate-500">Layoff notices</span>
          </Link>
          <div className="flex items-center gap-3">
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
            <AccountArea />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-3 text-xs text-slate-500">
          Data from US state WARN Act listings · scraped daily ·{" "}
          <a className="hover:underline" href="/docs">
            API docs
          </a>
        </div>
      </footer>
    </div>
  );
}
