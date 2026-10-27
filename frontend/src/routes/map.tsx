import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";

import { api, type TimelineBucket } from "../api/client";
import { FilterBar, type FilterValues } from "../components/FilterBar";
import { HeatLegend } from "../components/HeatLegend";
import { IndustryRace } from "../components/IndustryRace";
import { MapNoticePanel, type PanelSort } from "../components/MapNoticePanel";
import { MapPlaceSearch, type PlacePick } from "../components/MapPlaceSearch";
import {
  PlacesMap,
  type MapMode,
  type PlacesMapHandle,
  type SelectedPlace,
  type View,
} from "../components/PlacesMap";
import { PageHeader } from "../components/PageHeader";
import { SPEEDS, TimelineCard, type Speed } from "../components/TimelineCard";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useReducedMotion } from "../hooks/useReducedMotion";
import { useTheme } from "../hooks/useTheme";
import { fmtNum } from "../lib/format";
import { EMPTY_PLACES, placesBounds, stateOf, toGeoJSON } from "../lib/mapPlaces";
import {
  currentPeriod,
  DEFAULT_SINCE,
  framesGeoJSON,
  heatScaleMax,
  periodEnd,
  periodLabel,
  periodOf,
  periodStartMonth,
  placesOfTimeline,
  rollupIndustries,
  rollupPlaces,
  statesReporting,
  wholeWindow,
} from "../lib/timelapse";
import type { MapSearch } from "../router";

/* /map — every geocoded notice, period by period. The timeline card steps
   the map (bubbles or heat), the notice list and the industry ranking
   through periods; "All dates" is the aggregate view.

   Both timeline payloads load by month, once per filter set and window, and
   roll up here to the step on screen: a step change costs no request, and a
   window change keeps the current frame up while the wider one loads. */

// Base time per frame at 1x; finer buckets have more frames, so move faster.
const FRAME_MS: Record<TimelineBucket, number> = { year: 1400, quarter: 800, month: 300 };

const FILTER_KEYS = [
  "state",
  "closure_category",
  "industry",
  "subsector",
  "min_layoffs",
  "after",
  "before",
] as const;

/** The period a URL opens on. A bare /map opens on the last complete period
 *  (null: resolved once the frames load). A URL with filters but no
 *  timeline params predates the timeline -- an old shared link -- and keeps
 *  the all-dates view it showed then. */
function initialAt(search: MapSearch): string | null {
  if (search.at) return search.at;
  const legacy =
    search.bucket == null && search.since == null && FILTER_KEYS.some((k) => search[k] != null);
  return legacy ? "all" : null;
}

type Tab = "notices" | "industries";

export function MapPage() {
  useDocumentTitle("Layoff map — WARN Index");
  const { resolved } = useTheme();
  const navigate = useNavigate({ from: "/map" });
  const search = useSearch({ from: "/map" });
  const mode: MapMode = search.mode === "heat" ? "heat" : "bubbles";
  const bucket: TimelineBucket = search.bucket ?? "quarter";
  const since = search.since ?? DEFAULT_SINCE;
  const reducedMotion = useReducedMotion();
  const mapRef = useRef<PlacesMapHandle>(null);
  const columnRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState<SelectedPlace | null>(null);
  const [sort, setSort] = useState<PanelSort>("notice_date");
  const [tab, setTab] = useState<Tab>("notices");
  // Seeded once: later URL changes come *from* the map, not to it.
  const [initial] = useState(() =>
    search.lat != null && search.lon != null
      ? { lat: search.lat, lon: search.lon, zoom: search.zoom ?? 4 }
      : null,
  );

  // The frame is a period key, not an index, so it survives a step or
  // window change (re-keyed to the period holding the same month).
  const [at, setAt] = useState<string | null>(() => initialAt(search));
  const allDates = at === "all";
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(SPEEDS[1]);

  const filters = useMemo(
    () => ({
      state: search.state,
      closure_category: search.closure_category,
      industry: search.industry,
      subsector: search.subsector,
      min_layoffs: search.min_layoffs,
      after: search.after,
      before: search.before,
    }),
    [
      search.state,
      search.closure_category,
      search.industry,
      search.subsector,
      search.min_layoffs,
      search.after,
      search.before,
    ],
  );
  // On phones the filter card would fill the first screen, so it starts
  // folded behind a toggle that says how many filters are on.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const activeFilters = [
    filters.state,
    filters.closure_category,
    filters.industry ?? filters.subsector,
    filters.min_layoffs,
    filters.after ?? filters.before,
  ].filter((v) => v != null).length;

  // The timeline covers the window, narrowed by any date filter.
  const windowStart = `${since}-01-01`;
  const windowAfter = filters.after && filters.after > windowStart ? filters.after : windowStart;

  const placesQuery = useQuery({
    queryKey: ["map-places", filters],
    queryFn: () => api.listMapPlaces(filters),
    enabled: allDates,
    placeholderData: keepPreviousData, // old places stay up while filters change
  });
  const placeTimelineQuery = useQuery({
    queryKey: ["map-timeline", "places", filters, windowAfter],
    queryFn: () => api.mapPlacesTimeline({ ...filters, after: windowAfter, bucket: "month" }),
    enabled: !allDates,
    placeholderData: keepPreviousData,
  });
  // The ranking and the per-frame totals: every notice in the window, with
  // or without an industry or a geocode, so not narrowed by industry.
  const industryQuery = useQuery({
    queryKey: ["map-timeline", "industries", filters.state, filters.closure_category, windowAfter, filters.before],
    queryFn: () =>
      api.statsIndustriesTimeline({
        bucket: "month",
        state: filters.state,
        closure_category: filters.closure_category,
        after: windowAfter,
        before: filters.before,
      }),
    placeholderData: keepPreviousData,
  });
  const statusQuery = useQuery({
    queryKey: ["scraper-runs", "status"],
    queryFn: () => api.listScraperStatus(),
  });
  const industriesQuery = useQuery({
    queryKey: ["stats", "industries"],
    queryFn: () => api.statsIndustries(),
  });

  const timeline = useMemo(
    () => (industryQuery.data ? rollupIndustries(industryQuery.data, bucket) : undefined),
    [industryQuery.data, bucket],
  );
  const placeTimeline = useMemo(
    () => (placeTimelineQuery.data ? rollupPlaces(placeTimelineQuery.data, bucket) : undefined),
    [placeTimelineQuery.data, bucket],
  );

  // A stray future-dated notice would add empty frames past today.
  const now = currentPeriod(bucket);
  const frames = useMemo(
    () => (timeline ? timeline.periods.filter((p) => p <= now) : []),
    [timeline, now],
  );
  const last = frames.length - 1;
  const partial = frames[last] === now;
  const lastComplete = partial && last > 0 ? last - 1 : last;
  const idx = allDates
    ? -1
    : at !== null && frames.includes(at)
      ? frames.indexOf(at)
      : at !== null && frames.length > 0 && at < frames[0]
        ? 0
        : lastComplete;
  const period = idx >= 0 ? frames[idx] : undefined;

  // A bare /map opens paused on the last complete period.
  useEffect(() => {
    if (at === null && frames.length > 0) setAt(frames[lastComplete]);
  }, [at, frames, lastComplete]);

  // Playback: one timer per frame, so a pause or a scrub cancels cleanly.
  useEffect(() => {
    if (!playing || frames.length === 0) return;
    if (idx >= last) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setAt(frames[idx + 1]), FRAME_MS[bucket] / speed);
    return () => clearTimeout(t);
  }, [playing, idx, last, frames, bucket, speed]);

  // The URL follows the frame only while paused: a navigate per tick would
  // re-render the route and flood history-replace calls.
  useEffect(() => {
    if (playing || at === null || at === search.at) return;
    navigate({ search: (prev) => ({ ...prev, at }), replace: true, resetScroll: false });
  }, [playing, at, search.at, navigate]);

  const mapFrames = useMemo(
    () => (placeTimeline ? framesGeoJSON(placeTimeline, frames) : null),
    [placeTimeline, frames],
  );
  const heatMax = useMemo(
    () => (placeTimeline ? heatScaleMax(placeTimeline) : undefined),
    [placeTimeline],
  );
  const aggregate = placesQuery.data;
  const aggregateGeo = useMemo(
    () => (aggregate ? toGeoJSON(aggregate) : EMPTY_PLACES),
    [aggregate],
  );
  const data = allDates ? aggregateGeo : (mapFrames?.[idx] ?? EMPTY_PLACES);
  // What place search ranks and jumps to: the places on the map's data.
  const searchPlaces = useMemo(
    () => (allDates ? aggregate : placeTimeline ? placesOfTimeline(placeTimeline) : undefined),
    [allDates, aggregate, placeTimeline],
  );

  // National totals per frame, from the ranking's payload.
  const totals = useMemo(
    () =>
      frames.map((_, i) =>
        (timeline?.sectors ?? []).reduce(
          (acc, s) => ({ notices: acc.notices + s.notices[i], workers: acc.workers + s.workers[i] }),
          { notices: 0, workers: 0 },
        ),
      ),
    [frames, timeline],
  );
  const reporting = useMemo(
    () => (statusQuery.data && period ? statesReporting(statusQuery.data, period) : null),
    [statusQuery.data, period],
  );

  // The selected place's counts in what the map shows (zero if none there).
  const selectedHere = useMemo(
    () =>
      selected
        ? (data.features.find(
            (f) => f.properties.lat === selected.lat && f.properties.lon === selected.lon,
          )?.properties ?? { ...selected, n: 0, w: 0 })
        : null,
    [selected, data],
  );

  // Totals for the visible area, from what the map shows — no request needed.
  const summary = useMemo(() => {
    let notices = 0;
    let workers = 0;
    if (view) {
      const b = view.bounds;
      for (const { properties: p } of data.features) {
        if (p.lat >= b.min_lat && p.lat <= b.max_lat && p.lon >= b.min_lon && p.lon <= b.max_lon) {
          notices += p.n;
          workers += p.w;
        }
      }
    }
    return { notices, workers };
  }, [data, view]);

  // The notice list follows the frame once it settles: while playing it
  // keeps the last paused period instead of a request per frame.
  const [listPeriod, setListPeriod] = useState(period);
  useEffect(() => {
    if (!playing) setListPeriod(period);
  }, [playing, period]);
  const listFilters = useMemo(() => {
    if (allDates || !listPeriod) return filters;
    const start = `${periodStartMonth(listPeriod)}-01`;
    const end = periodEnd(listPeriod);
    return {
      ...filters,
      after: filters.after && filters.after > start ? filters.after : start,
      before: filters.before && filters.before < end ? filters.before : end,
    };
  }, [allDates, listPeriod, filters]);

  // Mirror the viewport into the URL (replace: panning must not spam history)
  // so back/refresh/share land on the same view.
  const handleViewChange = useCallback(
    (v: View) => {
      setView(v);
      navigate({
        search: (prev) => ({ ...prev, lat: v.lat, lon: v.lon, zoom: v.zoom }),
        replace: true,
        resetScroll: false,
      });
    },
    [navigate],
  );

  const handleFilterChange = (next: FilterValues) => {
    // Keep the viewport, mode and timeline: a filter shouldn't move the map
    // or the frame.
    navigate({
      search: (prev) => ({
        ...next,
        employer: undefined,
        lat: prev.lat,
        lon: prev.lon,
        zoom: prev.zoom,
        mode: prev.mode,
        bucket: prev.bucket,
        since: prev.since,
        at: prev.at,
      }),
    });
  };

  const setMode = (m: MapMode) =>
    navigate({
      search: (prev) => ({ ...prev, mode: m === "heat" ? "heat" : undefined }),
      replace: true,
      resetScroll: false,
    });

  const togglePlay = () => {
    if (playing) return setPlaying(false);
    // From the default frame (or past it) there's nothing left to play but
    // the partial current period, so play the whole window from the start.
    if (allDates || idx >= lastComplete) setAt(frames[0]);
    setPlaying(true);
  };
  const scrub = (i: number) => {
    setPlaying(false);
    setAt(frames[i]);
  };
  const showAllDates = () => {
    setPlaying(false);
    setAt("all");
  };
  const setBucket = (b: TimelineBucket) => {
    const next = period ? periodOf(periodStartMonth(period), b) : at;
    setAt(next);
    navigate({
      search: (prev) => ({ ...prev, bucket: b === "quarter" ? undefined : b, at: next ?? undefined }),
      replace: true,
      resetScroll: false,
    });
  };
  const setSince = (y: number) =>
    navigate({
      search: (prev) => ({ ...prev, since: y === DEFAULT_SINCE ? undefined : y }),
      replace: true,
      resetScroll: false,
    });
  const setIndustry = (sector: string | null) =>
    navigate({
      search: (prev) => ({ ...prev, industry: sector ?? undefined, subsector: undefined }),
      replace: true,
      resetScroll: false,
    });

  const handlePick = (pick: PlacePick) => {
    if (!searchPlaces) return;
    if (pick.kind === "place") {
      const i = pick.index;
      const place = {
        lat: searchPlaces.lat[i],
        lon: searchPlaces.lon[i],
        n: searchPlaces.notices[i],
        w: searchPlaces.workers[i],
        label: searchPlaces.label[i],
      };
      setSelected(place);
      // Past the clustering cutoff (zoom 11), so the place shows as its own
      // point under the selection ring rather than inside a cluster's centroid.
      mapRef.current?.flyTo(place.lat, place.lon, 12);
      return;
    }
    // A state: frame the places it has notices at.
    const b = placesBounds(searchPlaces, (i) => stateOf(searchPlaces.label[i]) === pick.code);
    setSelected(null);
    if (b) mapRef.current?.fitBounds(b);
  };

  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const next: Tab = tab === "notices" ? "industries" : "notices";
    setTab(next);
    document.getElementById(`map-tab-${next}`)?.focus();
  };

  const chipStats = selectedHere ? { notices: selectedHere.n, workers: selectedHere.w } : summary;
  const label = period ? periodLabel(period) : "";
  const isPartial = partial && idx === last;
  const fetching = allDates ? placesQuery.isFetching : placeTimelineQuery.isFetching;
  const raceTimeline = allDates ? (timeline ? wholeWindow(timeline) : undefined) : timeline;
  const raceWhen = allDates ? `since ${since}` : label;

  return (
    <div className="space-y-4">
      <PageHeader
        kicker="Explore"
        title="Layoff map"
        lede="Every geocoded WARN notice, period by period. Press play or drag the timeline; tap a place to list its notices."
      />
      <div id="map-filters" className={filtersOpen ? "" : "hidden md:block"}>
        <FilterBar
          values={search}
          onChange={handleFilterChange}
          showEmployer={false}
          industries={industriesQuery.data}
        />
      </div>

      <TimelineCard
        frames={frames}
        idx={idx}
        partial={partial}
        totals={totals}
        reporting={reporting}
        covered={statusQuery.data?.length ?? 0}
        theme={resolved}
        playing={playing}
        onTogglePlay={togglePlay}
        onScrub={scrub}
        onAllDates={showAllDates}
        bucket={bucket}
        onBucket={setBucket}
        since={since}
        onSince={setSince}
        speed={speed}
        onSpeed={setSpeed}
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex w-full gap-2 sm:w-auto">
          <MapPlaceSearch places={searchPlaces} onPick={handlePick} />
          <button
            type="button"
            aria-expanded={filtersOpen}
            aria-controls="map-filters"
            onClick={() => setFiltersOpen((o) => !o)}
            className="shrink-0 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 md:hidden dark:border-slate-700 dark:text-slate-300"
          >
            Filters{activeFilters > 0 ? ` · ${activeFilters}` : ""}
          </button>
        </div>
        <div className="inline-flex rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900" role="group" aria-label="Map style">
          {(
            [
              ["bubbles", "Bubbles"],
              ["heat", "Heatmap"],
            ] as const
          ).map(([m, text]) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                mode === m
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
              }`}
            >
              {text}
            </button>
          ))}
        </div>
      </div>

      {/* grid-cols-1 = minmax(0, 1fr): an auto track would size to the map
          canvas, which then grows to fill the track — a resize feedback loop. */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="relative overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
          <PlacesMap
            ref={mapRef}
            data={data}
            mode={mode}
            theme={resolved}
            initial={initial}
            stateBubbles
            selected={selectedHere}
            heatMax={allDates ? undefined : heatMax}
            onViewChange={handleViewChange}
            onSelect={setSelected}
            className="h-[60svh] w-full bg-slate-100 md:h-[75vh] dark:bg-slate-900"
          />
          {period && (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-3 hidden rounded-lg bg-white/90 px-2.5 py-1 text-base font-semibold tabular-nums text-slate-900 shadow md:block dark:bg-slate-900/90 dark:text-slate-50"
            >
              {label}
              {isPartial && <span className="ml-1 text-xs font-medium text-slate-500">partial</span>}
            </div>
          )}
          {!allDates && mode === "heat" && <HeatLegend max={heatMax} />}
          {fetching && (
            <div className="pointer-events-none absolute bottom-3 right-3 rounded-full bg-white/90 px-2.5 py-1 text-xs text-slate-600 shadow dark:bg-slate-900/90 dark:text-slate-300">
              Loading…
            </div>
          )}
          {/* Phones: the list sits below the map — this says what's in it and
              takes you there. Top-left: the bottom edge holds the attribution,
              the top-right the controls. */}
          <button
            type="button"
            onClick={() => {
              setTab("notices");
              columnRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            className="absolute left-3 top-3 max-w-[calc(100%-4.5rem)] truncate rounded-full bg-slate-900/90 px-4 py-2 text-sm font-medium text-white shadow-lg md:hidden dark:bg-slate-100/90 dark:text-slate-900"
          >
            {selectedHere ? `${selectedHere.label}: ` : period ? `${label}: ` : ""}
            {fmtNum(chipStats.notices)} notices · {fmtNum(chipStats.workers)} workers ↓
          </button>
        </div>

        <div ref={columnRef} className="flex min-w-0 scroll-mt-4 flex-col gap-2 md:h-[75vh]">
          <div
            role="tablist"
            aria-label="Beside the map"
            onKeyDown={onTabKey}
            className="inline-flex self-start rounded-full border border-slate-200 bg-white p-0.5 dark:border-slate-800 dark:bg-slate-900"
          >
            {(
              [
                ["notices", "Notices"],
                ["industries", "Industries"],
              ] as const
            ).map(([t, text]) => (
              <button
                key={t}
                id={`map-tab-${t}`}
                type="button"
                role="tab"
                aria-selected={tab === t}
                aria-controls={`map-tabpanel-${t}`}
                tabIndex={tab === t ? 0 : -1}
                onClick={() => setTab(t)}
                className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                  tab === t
                    ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
                }`}
              >
                {text}
              </button>
            ))}
          </div>
          {tab === "notices" ? (
            <div
              id="map-tabpanel-notices"
              role="tabpanel"
              aria-labelledby="map-tab-notices"
              className="flex min-h-0 flex-1 flex-col"
            >
              <MapNoticePanel
                filters={listFilters}
                bounds={view?.bounds ?? null}
                selected={selectedHere}
                summary={summary}
                sort={sort}
                onSortChange={setSort}
                onClearSelection={() => setSelected(null)}
                className="max-h-[80svh] md:max-h-none md:min-h-0 md:flex-1"
              />
            </div>
          ) : (
            <section
              id="map-tabpanel-industries"
              role="tabpanel"
              aria-labelledby="map-tab-industries"
              className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white p-3 sm:p-4 dark:border-slate-800 dark:bg-slate-900"
            >
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-50">
                Workers affected by industry, {raceWhen}
              </h2>
              {raceTimeline && (allDates || period) ? (
                <IndustryRace
                  timeline={raceTimeline}
                  frame={allDates ? 0 : idx}
                  theme={resolved}
                  selected={filters.industry ?? null}
                  onSelect={setIndustry}
                  transitionMs={reducedMotion ? 0 : Math.min(500, (FRAME_MS[bucket] / speed) * 0.8)}
                />
              ) : (
                <p className="mt-2 text-sm text-slate-500">Loading…</p>
              )}
            </section>
          )}
        </div>
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        {allDates
          ? aggregate
            ? `${fmtNum(aggregate.notices.reduce((a, b) => a + b, 0))} geocoded notices at ${fmtNum(aggregate.lat.length)} places match these filters. Most are placed at their city's center.`
            : placesQuery.isError
              ? "Couldn't load the map data."
              : "Loading map data…"
          : placeTimelineQuery.isError || industryQuery.isError
            ? "Couldn't load the timeline."
            : `Geocoded notices by filing date${
                filters.closure_category ? "" : ", leaving out Non-WARN events as the stats charts do"
              }. Most are placed at their city's center; the totals above the timeline count every notice.`}
      </p>
    </div>
  );
}
