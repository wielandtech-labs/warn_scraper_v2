import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer, useMapEvents } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";

import { api } from "../api/client";
import { FilterBar, type FilterValues } from "../components/FilterBar";
import { fmtDate, fmtNum } from "../lib/format";

// react-leaflet's default marker icons don't resolve correctly under
// Vite's bundler. Override with explicit asset URLs.
const DefaultIcon = L.icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

const CENTER_US: [number, number] = [39.5, -98.35];
const PIN_CAP = 50_000; // mirrors the /map-pins ceiling

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

// Reports the current map viewport up to the parent. Lives inside MapContainer
// (react-leaflet hooks require the map context). moveend/zoomend fire once at
// the end of a pan/zoom gesture, so this is naturally throttled — no debounce
// needed. A mount effect seeds the bounds so the first fetch is viewport-scoped.
function ViewportWatcher({ onChange }: { onChange: (b: Bbox) => void }) {
  const map = useMapEvents({
    moveend: () => onChange(boundsToBbox(map.getBounds())),
    zoomend: () => onChange(boundsToBbox(map.getBounds())),
  });
  useEffect(() => {
    onChange(boundsToBbox(map.getBounds()));
  }, [map, onChange]);
  return null;
}

export function MapPage() {
  const navigate = useNavigate({ from: "/map" });
  const search = useSearch({ from: "/map" });
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const handleBounds = useCallback((b: Bbox) => setBbox(b), []);

  const filters = {
    state: search.state,
    closure_category: search.closure_category,
    industry: search.industry,
    subsector: search.subsector,
    after: search.after,
    before: search.before,
  };

  // Pins for the current viewport. As the user zooms/pans, the bbox shrinks and
  // the API returns only what's visible — so the map scales past the cap.
  const query = useQuery({
    queryKey: ["map-pins", filters, bbox],
    queryFn: () => api.listMapPins({ ...filters, ...(bbox ?? {}) }),
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
    navigate({ search: () => ({ ...next, employer: undefined }) });
  };

  // Every item from listMapPins is guaranteed to have lat/lon — no client filter needed.
  const points = query.data ?? [];
  const total = totalQuery.data;
  const capped = points.length >= PIN_CAP;

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
          center={CENTER_US}
          zoom={4}
          scrollWheelZoom
          style={{ height: "70vh", width: "100%", position: "relative" }}
        >
          <ViewportWatcher onChange={handleBounds} />
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MarkerClusterGroup chunkedLoading>
            {points.map((n) => (
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
                    <a
                      href={`/notices/${encodeURIComponent(n.notice_id)}`}
                      className="mt-1 inline-block text-sky-700 hover:underline"
                    >
                      Details →
                    </a>
                  </div>
                </Popup>
              </Marker>
            ))}
          </MarkerClusterGroup>
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
