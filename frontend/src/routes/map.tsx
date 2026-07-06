import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer, useMapEvents } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";

import { api } from "../api/client";
import { FilterBar, type FilterValues } from "../components/FilterBar";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtDate, fmtNum } from "../lib/format";
import "../lib/leafletIcon"; // sets the default marker icon (Vite asset fix)

const CENTER_US: [number, number] = [39.5, -98.35];
// Per-device pin ceilings. The API tops out at 50 000, but instantiating that
// many Leaflet markers locks up a phone — so we request far fewer, smaller still
// on small screens. Newest-first ordering means low zoom shows the most recent
// pins; zooming in shrinks the bbox so a region still loads in full.
const MOBILE_PIN_CAP = 3_000;
const DESKTOP_PIN_CAP = 10_000;

interface Bbox {
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
}

// ~11 m precision; keeps the query key stable so tiny float jitter doesn't refetch.
const round = (n: number) => Math.round(n * 1e4) / 1e4;

const boundsToBbox = (b: L.LatLngBounds): Bbox => ({
  min_lat: round(b.getSouth()),
  min_lon: round(b.getWest()),
  max_lat: round(b.getNorth()),
  max_lon: round(b.getEast()),
});

// Fraction to expand the fetched bounds beyond the visible viewport on each
// side. Panning stays served from this buffer until the view leaves it, so
// ordinary dragging doesn't refetch.
const FETCH_BUFFER = 0.5;

interface Viewport {
  bounds: L.LatLngBounds; // visible bounds (unbuffered) — used for containment
  lat: number; // center
  lon: number;
  zoom: number;
}

const toViewport = (map: L.Map): Viewport => {
  const c = map.getCenter();
  return {
    bounds: map.getBounds(),
    lat: round(c.lat),
    lon: round(c.lng),
    zoom: map.getZoom(),
  };
};

// Reports the current map viewport up to the parent. Lives inside MapContainer
// (react-leaflet hooks require the map context). moveend/zoomend fire once at
// the end of a pan/zoom gesture, so this is naturally throttled — no debounce
// needed. A mount effect seeds the bounds so the first fetch is viewport-scoped.
function ViewportWatcher({ onChange }: { onChange: (v: Viewport) => void }) {
  const map = useMapEvents({
    moveend: () => onChange(toViewport(map)),
    zoomend: () => onChange(toViewport(map)),
  });
  useEffect(() => {
    onChange(toViewport(map));
  }, [map, onChange]);
  return null;
}

export function MapPage() {
  useDocumentTitle("Layoff map — WARN Tracker");
  const navigate = useNavigate({ from: "/map" });
  const search = useSearch({ from: "/map" });
  const [bbox, setBbox] = useState<Bbox | null>(null);
  // The buffered bounds + zoom the current `bbox` was fetched for. While the
  // visible view stays inside these at the same zoom, panning needs no refetch.
  const fetched = useRef<{ bounds: L.LatLngBounds; zoom: number } | null>(null);
  // Chosen once on mount; crossing the 640px line via resize/orientation is rare
  // enough not to warrant a media-query subscription.
  const [pinCap] = useState(() =>
    window.matchMedia("(max-width: 639px)").matches ? MOBILE_PIN_CAP : DESKTOP_PIN_CAP,
  );

  // Mirror the viewport into the URL (replace: panning must not spam history)
  // so back/refresh/share land on the same view. The pins query only refetches
  // when the visible view leaves the buffered region we last fetched, or the
  // zoom changes — so dragging within the buffer reuses the loaded pins.
  const handleViewport = useCallback(
    (v: Viewport) => {
      navigate({
        search: (prev) => ({ ...prev, lat: v.lat, lon: v.lon, zoom: v.zoom }),
        replace: true,
        resetScroll: false, // panning the map must not scroll the page to top
      });
      const prev = fetched.current;
      if (!prev || prev.zoom !== v.zoom || !prev.bounds.contains(v.bounds)) {
        const buffered = v.bounds.pad(FETCH_BUFFER);
        fetched.current = { bounds: buffered, zoom: v.zoom };
        setBbox(boundsToBbox(buffered));
      }
    },
    [navigate],
  );

  const filters = {
    state: search.state,
    closure_category: search.closure_category,
    industry: search.industry,
    subsector: search.subsector,
    after: search.after,
    before: search.before,
  };

  // Pins for the buffered region around the current viewport. Zooming in shrinks
  // the bbox so the API returns only what's visible — the map scales past the cap.
  const query = useQuery({
    queryKey: ["map-pins", filters, bbox, pinCap],
    queryFn: () => api.listMapPins({ ...filters, ...(bbox ?? {}), limit: pinCap }),
    enabled: bbox !== null,
    placeholderData: (prev) => prev, // keep old pins on screen during a refetch
  });

  // Total geocoded notices matching the (non-spatial) filters, for an honest
  // "showing X of Y" — Page.total from /notices mirrors the map-pins filters.
  const totalQuery = useQuery({
    queryKey: ["map-pins-total", filters],
    queryFn: () =>
      api.listNotices({ ...filters, geocoded_only: true, limit: 1 }).then((p) => p.total),
  });

  const industriesQuery = useQuery({
    queryKey: ["stats", "industries"],
    queryFn: () => api.statsIndustries(),
  });

  const handleFilterChange = (next: FilterValues) => {
    // Keep the viewport params — changing a filter shouldn't move the map.
    navigate({
      search: (prev) => ({
        ...next,
        employer: undefined,
        lat: prev.lat,
        lon: prev.lon,
        zoom: prev.zoom,
      }),
    });
  };

  // Every item from listMapPins is guaranteed to have lat/lon — no client filter needed.
  const points = query.data ?? [];
  const total = totalQuery.data;
  const capped = points.length >= pinCap;

  // Memoized on `points` only: every pan mirrors the viewport into the URL,
  // which re-renders this component via useSearch — without the memo, React
  // re-reconciles up to 10k <Marker> elements (and the fresh position arrays
  // make react-leaflet call setLatLng on every one) on every pan, even when
  // nothing refetched. React Query keeps `points` referentially stable
  // between refetches (placeholderData included), so this bails out of the
  // whole marker subtree unless the data actually changed.
  const markers = useMemo(
    () =>
      points.map((n) => (
        <Marker
          key={n.notice_id}
          position={[Number(n.lat), Number(n.lon)]}
        >
          <Popup>
            <div className="text-sm">
              <div className="font-semibold">{n.employer}</div>
              <div className="text-slate-600">
                {n.state} · {fmtDate(n.notice_date)}
              </div>
              <div className="mt-1">
                {fmtNum(n.layoff_count)} affected
              </div>
              <Link
                to="/notices/$noticeId"
                params={{ noticeId: n.notice_id }}
                className="mt-1 inline-block text-sky-700 hover:underline"
              >
                Details →
              </Link>
            </div>
          </Popup>
        </Marker>
      )),
    [points],
  );

  return (
    <div>
      <h1 className="mb-3 text-2xl font-semibold">Map</h1>
      <FilterBar
        values={search}
        onChange={handleFilterChange}
        showEmployer={false}
        industries={industriesQuery.data}
      />

      <div className="overflow-hidden rounded-lg border border-slate-200">
        <MapContainer
          center={search.lat != null && search.lon != null ? [search.lat, search.lon] : CENTER_US}
          zoom={search.zoom ?? 4}
          scrollWheelZoom
          style={{ height: "70vh", width: "100%", position: "relative" }}
        >
          <ViewportWatcher onChange={handleViewport} />
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MarkerClusterGroup chunkedLoading>{markers}</MarkerClusterGroup>
        </MapContainer>
      </div>

      <div className="mt-2 text-xs text-slate-500">
        Showing {fmtNum(points.length)}
        {total != null && ` of ${fmtNum(total)}`} geocoded notices in view.
        {capped && " Zoom in to load all pins in a region."}
      </div>
    </div>
  );
}
