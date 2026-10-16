import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api } from "../api/client";
import { useTheme } from "../hooks/useTheme";
import { fmtNum } from "../lib/format";
import { EMPTY_PLACES, placesBounds, toGeoJSON } from "../lib/mapPlaces";
import type { PlacesMap as PlacesMapComponent, PlacesMapHandle, SelectedPlace } from "./PlacesMap";

// MapLibre is a ~300 KB gzip chunk plus its worker, and on the state and
// sector pages the map sits below the fold. Fetch it only once the map nears
// the viewport, so a visit that never scrolls there never pays for it.
// If the chunk fails (offline, or a deploy replaced the hashed file since
// this page loaded), say so inside the map box rather than letting the
// rejection take down the whole page.
const PlacesMap = lazy(() =>
  import("./PlacesMap").then(
    (m) => ({ default: m.PlacesMap }),
    // The fallback ignores the map's props and ref.
    () => ({ default: MapLoadFailed as unknown as typeof PlacesMapComponent }),
  ),
);

function MapLoadFailed() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-slate-500 dark:text-slate-400">
      The map couldn't load. Reload the page to try again.
    </div>
  );
}

const noop = () => {};

/** True once the element comes within `rootMargin` of the viewport; stays
 *  true. A callback ref, so it follows the element across re-renders (the
 *  loading box is replaced by the map box). */
function useNearViewport(rootMargin = "400px") {
  const [el, setEl] = useState<Element | null>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    if (near || !el) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setNear(true);
      },
      { rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [el, near, rootMargin]);
  return [setEl, near] as const;
}

/** Bubble map of geocoded notices for one state and/or NAICS sector, scoped
 *  to a time window, fitted to its places. The same map and data as /map;
 *  tapping a place links there for the notices behind it. */
export function NoticeMap({
  state,
  industry,
  after,
  before,
  height = "60vh",
}: {
  state?: string;
  industry?: string;
  after?: string;
  before?: string;
  height?: string;
}) {
  const { resolved } = useTheme();
  const [boxRef, near] = useNearViewport();
  const mapRef = useRef<PlacesMapHandle>(null);
  const [selected, setSelected] = useState<SelectedPlace | null>(null);
  const query = useQuery({
    queryKey: ["map-places", { state, industry, after, before }],
    queryFn: () => api.listMapPlaces({ state, industry, after, before }),
  });
  const places = query.data;
  const geojson = useMemo(() => (places ? toGeoJSON(places) : EMPTY_PLACES), [places]);

  const bounds = useMemo(() => places && placesBounds(places), [places]);

  // The map mounts already fitted to the set it first shows (`initial`
  // below) — calling fitBounds during mount gets lost. Refit only when the
  // set changes under a live map (e.g. the time window toggles), and drop a
  // selection that may no longer exist in it. No bounds = no map mounted.
  const fittedTo = useRef<typeof bounds>(null);
  useEffect(() => {
    const mounted = fittedTo.current;
    fittedTo.current = bounds ?? null;
    if (!mounted || !bounds || bounds === mounted) return;
    setSelected(null);
    mapRef.current?.fitBounds(bounds);
  }, [bounds]);

  if (query.isLoading) {
    return (
      <div ref={boxRef} className="flex items-center justify-center text-slate-500 dark:text-slate-400" style={{ height }}>
        Loading map…
      </div>
    );
  }
  if (!places || !bounds) {
    return (
      <div ref={boxRef} className="flex h-24 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
        No geocoded notices to map for this period.
      </div>
    );
  }

  const total = places.notices.reduce((a, b) => a + b, 0);
  return (
    <>
      {/* The bordered box holds its height while MapLibre loads, so the page doesn't jump. */}
      <div
        ref={boxRef}
        className="overflow-hidden rounded-lg border border-slate-200 bg-slate-100 dark:border-slate-800 dark:bg-slate-900"
        style={{ height }}
      >
        {near && (
          <Suspense fallback={null}>
            <PlacesMap
              ref={mapRef}
              data={geojson}
              mode="bubbles"
              theme={resolved}
              initial={{ bounds }}
              selected={selected}
              onViewChange={noop}
              onSelect={setSelected}
              className="h-full w-full bg-slate-100 dark:bg-slate-900"
            />
          </Suspense>
        )}
      </div>
      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        {selected ? (
          <>
            <span className="font-medium text-slate-700 dark:text-slate-200">{selected.label}</span>
            {" · "}
            {fmtNum(selected.n)} notices · {fmtNum(selected.w)} workers ·{" "}
            <Link
              to="/map"
              search={{ state, industry, after, before, lat: selected.lat, lon: selected.lon, zoom: 12 }}
              className="font-medium text-sky-700 hover:underline dark:text-sky-400"
            >
              List them on the map →
            </Link>
          </>
        ) : (
          <>
            {fmtNum(total)} geocoded notices at {fmtNum(places.lat.length)} places. Tap a bubble for its
            notices.
          </>
        )}
      </div>
    </>
  );
}
