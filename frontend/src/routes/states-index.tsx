import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";

import { api } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { QueryError } from "../components/QueryError";
import { StateSilhouette } from "../components/StateSilhouette";
import { TimeRangeToggle, toRangeQuery, type TimeRange } from "../components/TimeRangeToggle";
import { type ChoroplethMetric, UsChoroplethMap } from "../components/UsChoroplethMap";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { STATE_NAMES, US_STATES, fmtNum } from "../lib/format";
import { NO_COUNTS, UNSUPPORTED, isUnpublished } from "../lib/unavailable";

const METRICS: { id: ChoroplethMetric; label: string }[] = [
  { id: "workers", label: "Workers" },
  { id: "notices", label: "Notices" },
];

// Completes "… workers affected ___".
const RANGE_PHRASE: Record<TimeRange, string> = {
  "30d": "in the last 30 days",
  "1y": "in the last year",
  "5y": "in the last five years",
  all: "since records began",
};

const TOP_N = 10;

interface Row {
  code: string;
  name: string;
  notice_count: number;
  layoff_total: number;
  value: number;
}

export function StatesIndexPage() {
  useDocumentTitle("Layoffs by state — WARN Index");
  const navigate = useNavigate({ from: "/states" });
  const search = useSearch({ from: "/states" });
  // A year by default: all-time totals mostly measure how far back each
  // state's archive reaches, not how much it is laying off.
  const range: TimeRange = search.range ?? "1y";
  const metric: ChoroplethMetric = search.metric ?? "workers";
  const sortByName = search.sort === "name";
  const [hovered, setHovered] = useState<string | null>(null);
  const [find, setFind] = useState("");

  const { after } = toRangeQuery(range);
  const byState = useQuery({
    queryKey: ["stats", "by-state", { after }],
    queryFn: () => api.statsByState({ after }),
    // Keep the previous range's map on screen while the next one loads.
    placeholderData: (prev) => prev,
  });

  // Index the aggregate by state code; states with no notices still render
  // (zeros), so every jurisdiction has a browsable, internally-linked page.
  const stats = new Map((byState.data ?? []).map((s) => [s.state, s]));
  const all: Row[] = US_STATES.map((code) => {
    const notice_count = stats.get(code)?.notice_count ?? 0;
    const layoff_total = stats.get(code)?.layoff_total ?? 0;
    return {
      code,
      name: STATE_NAMES[code],
      notice_count,
      layoff_total,
      value: metric === "notices" ? notice_count : layoff_total,
    };
  });
  // States with no figure for this metric sit outside the ranking (listed in
  // a footnote) instead of trailing it as zeros they never reported.
  const ranked = all
    .filter((r) => !isUnpublished(r.code, metric))
    .sort((a, b) => b.value - a.value || a.name.localeCompare(b.name));
  const unpublished = all.filter((r) => isUnpublished(r.code, metric));
  const rankOf = new Map(ranked.map((r, i) => [r.code, i + 1]));
  const total = ranked.reduce((a, r) => a + r.value, 0);
  const barMax = Math.max(1, ranked[0]?.value ?? 0);
  const top = ranked.slice(0, TOP_N).filter((r) => r.value > 0);

  const needle = find.trim().toLowerCase();
  const cards = (sortByName ? [...ranked].sort((a, b) => a.name.localeCompare(b.name)) : ranked)
    .filter((r) => !needle || r.name.toLowerCase().includes(needle) || r.code.toLowerCase() === needle);

  const reporting = (byState.data ?? []).filter((s) => s.notice_count > 0).length;
  const totalWorkers = (byState.data ?? []).reduce((a, s) => a + s.layoff_total, 0);
  const metricNoun = metric === "notices" ? "notices" : "workers";

  const setSearch = (patch: Partial<typeof search>) =>
    navigate({ search: (prev) => ({ ...prev, ...patch }) });

  return (
    <div className="space-y-6">
      <PageHeader
        kicker="50 states + DC"
        title="Layoffs by state"
        lede={
          // While the next range loads, the previous range's total would sit
          // under the new range's wording; fall back to the generic lede.
          byState.data && !byState.isPlaceholderData ? (
            <>
              <span className="font-semibold text-slate-900 dark:text-slate-100">
                {fmtNum(totalWorkers)}
              </span>{" "}
              workers affected {RANGE_PHRASE[range]}, across {reporting} jurisdictions with WARN
              filings. Open a state for its trend, top employers and latest filings.
            </>
          ) : (
            "Browse WARN Act layoff and closure notices for each US state and DC."
          )
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <TimeRangeToggle
          value={range}
          onChange={(r) => setSearch({ range: r === "1y" ? undefined : r })}
        />
        <div
          role="group"
          aria-label="Measure"
          className="inline-flex rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900"
        >
          {METRICS.map((m) => (
            <button
              key={m.id}
              type="button"
              aria-pressed={metric === m.id}
              onClick={() => setSearch({ metric: m.id === "notices" ? "notices" : undefined })}
              className={
                "rounded-full px-3 py-1 text-sm font-medium transition-colors " +
                (metric === m.id
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100")
              }
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {byState.isLoading && (
        <div aria-hidden className="grid gap-4 lg:grid-cols-5">
          <div className="card h-80 animate-pulse lg:col-span-3" />
          <div className="card h-80 animate-pulse lg:col-span-2" />
        </div>
      )}

      {byState.isError && (
        <QueryError
          message="Error loading state totals."
          onRetry={() => byState.refetch()}
        />
      )}

      {/* Don't render until data arrives — with no data every state would
          confidently show zeros. */}
      {byState.data && (
        <div
          className={
            "space-y-6 transition-opacity " + (byState.isPlaceholderData ? "opacity-60" : "")
          }
        >
          <div className="grid gap-4 lg:grid-cols-5">
            <section className="card flex flex-col justify-center lg:col-span-3" aria-label="Map">
              <UsChoroplethMap
                data={all}
                metric={metric}
                highlight={hovered}
                onHover={setHovered}
              />
            </section>

            <section className="card flex flex-col lg:col-span-2">
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="text-lg font-semibold">Top {TOP_N}</h2>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {metricNoun}, {RANGE_PHRASE[range].replace(/^in the /, "")}
                </span>
              </div>
              {top.length === 0 ? (
                <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">
                  No filings in this window.
                </p>
              ) : (
                <ol className="mt-3 flex-1 divide-y divide-slate-100 dark:divide-slate-800">
                  {top.map((r, i) => (
                    <li key={r.code}>
                      <Link
                        to="/states/$state"
                        params={{ state: r.code }}
                        onMouseEnter={() => setHovered(r.code)}
                        onMouseLeave={() => setHovered(null)}
                        onFocus={() => setHovered(r.code)}
                        onBlur={() => setHovered(null)}
                        className={
                          "group grid grid-cols-[1.25rem_1.25rem_minmax(0,1fr)_auto] items-center gap-x-2.5 rounded-md px-1.5 py-2 transition-colors " +
                          (hovered === r.code
                            ? "bg-slate-100 dark:bg-slate-800"
                            : "hover:bg-slate-100 dark:hover:bg-slate-800")
                        }
                      >
                        <span className="text-right text-xs tabular-nums text-slate-400">
                          {i + 1}
                        </span>
                        <StateSilhouette
                          code={r.code}
                          size={20}
                          className="text-slate-300 group-hover:text-brand dark:text-slate-600"
                        />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                            {r.name}
                          </span>
                          <span
                            aria-hidden
                            className="mt-1 block h-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"
                          >
                            <span
                              className={`block h-full rounded-full ${metric === "notices" ? "bg-sky-500/70" : "bg-brand/70"}`}
                              style={{ width: `${(r.value / barMax) * 100}%` }}
                            />
                          </span>
                        </span>
                        <span className="text-right">
                          <span className="block text-sm font-semibold tabular-nums">
                            {fmtNum(r.value)}
                          </span>
                          <span className="block text-xs tabular-nums text-slate-500 dark:text-slate-400">
                            {total ? `${((r.value / total) * 100).toFixed(1)}%` : "—"}
                          </span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>

          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Every jurisdiction</h2>
              <div className="flex items-center gap-2">
                <input
                  type="search"
                  value={find}
                  onChange={(e) => setFind(e.target.value)}
                  placeholder="Find a state…"
                  aria-label="Find a state"
                  className="h-8 w-40 rounded-full border border-slate-300 px-3 text-sm dark:border-slate-700 dark:bg-slate-900"
                />
                <select
                  aria-label="Sort states"
                  value={sortByName ? "name" : "value"}
                  onChange={(e) =>
                    setSearch({ sort: e.target.value === "name" ? "name" : undefined })
                  }
                  className="h-8 rounded-full border border-slate-300 px-3 text-sm dark:border-slate-700 dark:bg-slate-900"
                >
                  <option value="value">Most {metricNoun}</option>
                  <option value="name">A–Z</option>
                </select>
              </div>
            </div>

            {cards.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No state matches “{find}”.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {cards.map((s) => (
                  <Link
                    key={s.code}
                    to="/states/$state"
                    params={{ state: s.code }}
                    onMouseEnter={() => setHovered(s.code)}
                    onMouseLeave={() => setHovered(null)}
                    onFocus={() => setHovered(s.code)}
                    onBlur={() => setHovered(null)}
                    className="card group flex flex-col gap-2.5 !p-4 transition-colors hover:border-slate-300 dark:hover:border-slate-700"
                  >
                    <div className="flex items-center gap-3">
                      <StateSilhouette
                        code={s.code}
                        size={32}
                        className="shrink-0 text-slate-300 transition-colors group-hover:text-brand dark:text-slate-600"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium text-slate-900 dark:text-slate-100">
                          {s.name}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">
                          #{rankOf.get(s.code)} ·{" "}
                          {metric === "workers"
                            ? `${fmtNum(s.notice_count)} ${s.notice_count === 1 ? "notice" : "notices"}`
                            : s.code in NO_COUNTS
                              ? "worker counts not published"
                              : `${fmtNum(s.layoff_total)} workers`}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-display text-lg font-semibold tabular-nums">
                          {fmtNum(s.value)}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">
                          {metricNoun}
                        </div>
                      </div>
                    </div>
                    <div
                      aria-hidden
                      className="h-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"
                    >
                      <div
                        // Entity colors, as in the charts: workers red, notices blue.
                        className={`h-full rounded-full ${metric === "notices" ? "bg-sky-500/70" : "bg-brand/70"}`}
                        style={{ width: `${(s.value / barMax) * 100}%` }}
                      />
                    </div>
                  </Link>
                ))}
              </div>
            )}

            {unpublished.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 pt-1 text-sm">
                <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  {metric === "notices" ? "No notices published" : "No worker counts published"}                </span>
                {unpublished.map((s) => (
                  <Link
                    key={s.code}
                    to="/states/$state"
                    params={{ state: s.code }}
                    title={UNSUPPORTED[s.code] ?? NO_COUNTS[s.code]}
                    className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-slate-300 px-2.5 py-0.5 text-slate-600 hover:border-slate-400 hover:text-slate-900 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100"
                  >
                    <StateSilhouette code={s.code} size={14} className="text-slate-300 dark:text-slate-600" />
                    {s.name}
                  </Link>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
