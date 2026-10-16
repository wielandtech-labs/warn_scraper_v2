import { forwardRef } from "react";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import { api, type MapPlacesQuery } from "../api/client";
import { fmtNum } from "../lib/format";
import { NoticeList } from "./NoticeList";
import type { SelectedPlace, View } from "./PlacesMap";

const PAGE = 25;

/** The (inclusive) range of 6-dp coordinates that the API's 4-dp rounding
 *  maps to `p` — i.e. exactly the locations aggregated into that place.
 *  Postgres rounds half away from zero, so the half-step boundary belongs to
 *  the cell nearer zero on each side: [p-5e-5, p+4.9e-5] for p >= 0. The
 *  1e-9 slack absorbs float error at the inclusive edge. */
function roundingCell(p: number): [number, number] {
  return p >= 0 ? [p - 5e-5 - 1e-9, p + 4.9e-5] : [p - 4.9e-5, p + 5e-5 + 1e-9];
}

export type PanelSort = "notice_date" | "layoff_count";

/* The notices behind the map: those at the selected place, or else those in
   the current view. The map shows where; this is the accessible, readable
   list of what — and the only way into a notice from the map. */
export const MapNoticePanel = forwardRef<
  HTMLElement,
  {
    filters: MapPlacesQuery;
    bounds: View["bounds"] | null;
    selected: SelectedPlace | null;
    summary: { notices: number; workers: number };
    sort: PanelSort;
    onSortChange: (s: PanelSort) => void;
    onClearSelection: () => void;
    className?: string;
  }
>(function MapNoticePanel(
  { filters, bounds, selected, summary, sort, onSortChange, onClearSelection, className },
  ref,
) {
  const box = selected
    ? (() => {
        const [min_lat, max_lat] = roundingCell(selected.lat);
        const [min_lon, max_lon] = roundingCell(selected.lon);
        return { min_lat, max_lat, min_lon, max_lon };
      })()
    : bounds;

  const list = useInfiniteQuery({
    queryKey: ["map-notices", filters, box, sort],
    queryFn: ({ pageParam }) =>
      api.listNotices({
        ...filters,
        ...box!,
        sort_by: sort,
        sort_dir: "desc",
        limit: PAGE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined,
    enabled: box !== null,
    placeholderData: keepPreviousData, // no flash to empty while panning
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total ?? 0;

  const heading = selected ? selected.label : "In this view";
  const stats = selected ? { notices: selected.n, workers: selected.w } : summary;

  return (
    <section
      ref={ref}
      aria-label="Notices on the map"
      className={`flex flex-col rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 ${className ?? ""}`}
    >
      <header className="space-y-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="truncate font-semibold text-slate-900 dark:text-slate-100">{heading}</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {fmtNum(stats.notices)} notices · {fmtNum(stats.workers)} workers
            </p>
          </div>
          {selected && (
            <button
              type="button"
              onClick={onClearSelection}
              className="shrink-0 rounded-full border border-slate-300 px-2.5 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              ✕ Whole view
            </button>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-xs" role="group" aria-label="Sort notices">
          <span className="text-slate-400">Sort:</span>
          {(
            [
              ["notice_date", "Newest"],
              ["layoff_count", "Largest"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={sort === value}
              onClick={() => onSortChange(value)}
              className={`rounded-full px-2.5 py-0.5 font-medium transition-colors ${
                sort === value
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "border border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800/50"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto" aria-busy={list.isFetching}>
        {list.isError ? (
          <p className="px-4 py-6 text-sm text-slate-500">Couldn't load notices.</p>
        ) : items.length === 0 ? (
          <p className="px-4 py-6 text-sm text-slate-500 dark:text-slate-400">
            {list.isPending ? "Loading notices…" : "No geocoded notices here. Zoom out or widen the filters."}
          </p>
        ) : (
          <>
            <NoticeList notices={items} lead="employer" />
            {list.hasNextPage && (
              <div className="border-t border-slate-100 px-4 py-3 dark:border-slate-800">
                <button
                  type="button"
                  disabled={list.isFetchingNextPage}
                  onClick={() => list.fetchNextPage()}
                  className="text-sm font-medium text-sky-700 hover:underline disabled:opacity-50 dark:text-sky-400"
                >
                  {list.isFetchingNextPage
                    ? "Loading…"
                    : `Show more (${fmtNum(total - items.length)} left)`}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
});
