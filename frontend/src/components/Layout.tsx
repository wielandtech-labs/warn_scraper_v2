import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/notices", label: "Notices" },
  { to: "/companies", label: "Companies" },
  { to: "/map", label: "Map" },
  { to: "/stats", label: "Stats" },
];

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-semibold tracking-tight text-slate-900">
            WARN <span className="text-sky-600">·</span>{" "}
            <span className="font-normal text-slate-500">Layoff notices</span>
          </Link>
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
