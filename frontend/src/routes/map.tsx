import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";

import { api } from "../api/client";
import { FilterBar, type FilterValues } from "../components/FilterBar";
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
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useTheme } from "../hooks/useTheme";
import { fmtNum } from "../lib/format";
import { EMPTY_PLACES, placesBounds, stateOf, toGeoJSON } from "../lib/mapPlaces";

// The earliest year any state's backfill reaches (IL, 1999).
const FIRST_YEAR = 1999;
const THIS_YEAR = new Date().getFullYear();
// The slider's last notch, past the current year, means "any year": resting
// the thumb on THIS_YEAR would make the current year unselectable (moving to
// the value it already shows fires no change).
const ANY_YEAR = THIS_YEAR + 1;

/** The calendar year the date filters select exactly, if they do. */
function selectedYear(after?: string, before?: string): number | null {
  const m = after?.match(/^(\d{4})-01-01$/);
  return m && before === `${m[1]}-12-31` ? Number(m[1]) : null;
}

export function MapPage() {
  useDocumentTitle("Layoff map — WARN Index");
  const { resolved } = useTheme();
  const navigate = useNavigate({ from: "/map" });
  const search = useSearch({ from: "/map" });
  const mode: MapMode = search.mode === "heat" ? "heat" : "bubbles";
  const mapRef = useRef<PlacesMapHandle>(null);
  const panelRef = useRef<HTMLElement>(null);
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState<SelectedPlace | null>(null);
  const [sort, setSort] = useState<PanelSort>("notice_date");
  // Seeded once: later URL changes come *from* the map, not to it.
  const [initial] = useState(() =>
    search.lat != null && search.lon != null
      ? { lat: search.lat, lon: search.lon, zoom: search.zoom ?? 4 }
      : null,
  );

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

  const placesQuery = useQuery({
    queryKey: ["map-places", filters],
    queryFn: () => api.listMapPlaces(filters),
    placeholderData: keepPreviousData, // old places stay up while filters change
  });
  const places = placesQuery.data;
  const geojson = useMemo(
    () => (places ? toGeoJSON(places) : EMPTY_PLACES),
    [places],
  );

  const industriesQuery = useQuery({
    queryKey: ["stats", "industries"],
    queryFn: () => api.statsIndustries(),
  });

  // New filters change every place's counts: carry the selection over with
  // fresh numbers, or drop it if the place no longer has matching notices.
  useEffect(() => {
    setSelected((sel) => {
      if (!sel || !places) return sel;
      const i = places.lat.findIndex((lat, j) => lat === sel.lat && places.lon[j] === sel.lon);
      return i < 0
        ? null
        : { ...sel, n: places.notices[i], w: places.workers[i], label: places.label[i] };
    });
  }, [places]);

  // Totals for the visible area, from the loaded places — no request needed.
  const summary = useMemo(() => {
    let notices = 0;
    let workers = 0;
    if (places && view) {
      const b = view.bounds;
      for (let i = 0; i < places.lat.length; i++) {
        const lat = places.lat[i];
        const lon = places.lon[i];
        if (lat >= b.min_lat && lat <= b.max_lat && lon >= b.min_lon && lon <= b.max_lon) {
          notices += places.notices[i];
          workers += places.workers[i];
        }
      }
    }
    return { notices, workers };
  }, [places, view]);

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
    // Keep the viewport and mode — changing a filter shouldn't move the map.
    navigate({
      search: (prev) => ({
        ...next,
        employer: undefined,
        lat: prev.lat,
        lon: prev.lon,
        zoom: prev.zoom,
        mode: prev.mode,
      }),
    });
  };

  const setMode = (m: MapMode) =>
    navigate({
      search: (prev) => ({ ...prev, mode: m === "heat" ? "heat" : undefined }),
      replace: true,
      resetScroll: false,
    });

  // Year slider: the URL only changes once the thumb rests, so dragging
  // across 25 years doesn't fire 25 fetches. Back on "Any" it clears the
  // year — only when a year was set, so other date filters are left alone.
  const urlYear = selectedYear(search.after, search.before);
  const [draftYear, setDraftYear] = useState<number | null>(urlYear);
  useEffect(() => setDraftYear(urlYear), [urlYear]);
  useEffect(() => {
    if (draftYear === urlYear) return;
    const t = setTimeout(
      () =>
        navigate({
          search: (prev) =>
            draftYear === null
              ? { ...prev, after: undefined, before: undefined }
              : { ...prev, after: `${draftYear}-01-01`, before: `${draftYear}-12-31` },
          resetScroll: false,
        }),
      300,
    );
    return () => clearTimeout(t);
  }, [draftYear, urlYear, navigate]);

  const handlePick = (pick: PlacePick) => {
    if (!places) return;
    if (pick.kind === "place") {
      const i = pick.index;
      const place = {
        lat: places.lat[i],
        lon: places.lon[i],
        n: places.notices[i],
        w: places.workers[i],
        label: places.label[i],
      };
      setSelected(place);
      // Past the clustering cutoff (zoom 11), so the place shows as its own
      // point under the selection ring rather than inside a cluster's centroid.
      mapRef.current?.flyTo(place.lat, place.lon, 12);
      return;
    }
    // A state: frame the places it has notices at.
    const b = placesBounds(places, (i) => stateOf(places.label[i]) === pick.code);
    setSelected(null);
    if (b) mapRef.current?.fitBounds(b);
  };

  const chipStats = selected ? { notices: selected.n, workers: selected.w } : summary;

  return (
    <div className="space-y-4">
      <PageHeader
        kicker="Explore"
        title="Layoff map"
        lede="Every geocoded WARN notice, grouped by place. Bubbles grow with the workers affected; tap one to list its notices."
        aside={
          <Link to="/timelapse" className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
            Watch it over time →
          </Link>
        }
      />
      <div id="map-filters" className={filtersOpen ? "" : "hidden md:block"}>
        <FilterBar
          values={search}
          onChange={handleFilterChange}
          showEmployer={false}
          industries={industriesQuery.data}
        />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex w-full gap-2 sm:w-auto">
          <MapPlaceSearch places={places} onPick={handlePick} />
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
          ).map(([m, label]) => (
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
              {label}
            </button>
          ))}
        </div>
        <label className="flex min-w-0 flex-1 items-center gap-2 text-sm sm:max-w-sm">
          <span className="shrink-0 text-slate-500 dark:text-slate-400">Year</span>
          <input
            type="range"
            min={FIRST_YEAR}
            max={ANY_YEAR}
            step={1}
            value={draftYear ?? ANY_YEAR}
            onChange={(e) => {
              const y = Number(e.target.value);
              setDraftYear(y === ANY_YEAR ? null : y);
            }}
            aria-valuetext={draftYear === null ? "Any year" : String(draftYear)}
            className={`min-w-0 flex-1 accent-brand ${draftYear === null ? "opacity-50" : ""}`}
          />
          <output className="w-16 shrink-0 tabular-nums text-slate-700 dark:text-slate-300">
            {draftYear ?? "Any"}
          </output>
        </label>
      </div>

      {/* grid-cols-1 = minmax(0, 1fr): an auto track would size to the map
          canvas, which then grows to fill the track — a resize feedback loop. */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="relative overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
          <PlacesMap
            ref={mapRef}
            data={geojson}
            mode={mode}
            theme={resolved}
            initial={initial}
            stateBubbles
            selected={selected}
            onViewChange={handleViewChange}
            onSelect={setSelected}
            className="h-[60svh] w-full bg-slate-100 md:h-[75vh] dark:bg-slate-900"
          />
          {placesQuery.isFetching && (
            <div className="pointer-events-none absolute bottom-3 left-3 rounded-full bg-white/90 px-2.5 py-1 text-xs text-slate-600 shadow dark:bg-slate-900/90 dark:text-slate-300">
              Loading…
            </div>
          )}
          {/* Phones: the list sits below the map — this says what's in it and
              takes you there. Top-left: the bottom edge holds the attribution,
              the top-right the controls. */}
          <button
            type="button"
            onClick={() => panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
            className="absolute left-3 top-3 max-w-[calc(100%-4.5rem)] truncate rounded-full bg-slate-900/90 px-4 py-2 text-sm font-medium text-white shadow-lg md:hidden dark:bg-slate-100/90 dark:text-slate-900"
          >
            {selected ? `${selected.label}: ` : ""}
            {fmtNum(chipStats.notices)} notices · {fmtNum(chipStats.workers)} workers ↓
          </button>
        </div>

        <MapNoticePanel
          ref={panelRef}
          filters={filters}
          bounds={view?.bounds ?? null}
          selected={selected}
          summary={summary}
          sort={sort}
          onSortChange={setSort}
          onClearSelection={() => setSelected(null)}
          className="max-h-[80svh] scroll-mt-4 md:h-[75vh] md:max-h-none"
        />
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        {places
          ? `${fmtNum(places.notices.reduce((a, b) => a + b, 0))} geocoded notices at ${fmtNum(places.lat.length)} places match these filters. Most are placed at their city's center.`
          : placesQuery.isError
            ? "Couldn't load the map data."
            : "Loading map data…"}
      </p>
    </div>
  );
}
