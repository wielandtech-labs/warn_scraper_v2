import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";

import { api, type MapPin } from "../api/client";
import { fmtDate, fmtNum } from "../lib/format";
import "../lib/leafletIcon"; // sets the default marker icon (Vite asset fix)

const CENTER_US: [number, number] = [39.5, -98.35];
// A single state's geocoded set is small, so we fetch it all and skip the
// global map's viewport-scoped paging. This ceiling is a safety cap.
const STATE_MAP_PIN_CAP = 5_000;

// Fits the map to the loaded pins whenever they change (e.g. the time window
// toggles). Lives inside MapContainer so it can use the react-leaflet map ctx.
function FitBounds({ points }: { points: MapPin[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    const bounds = L.latLngBounds(
      points.map((p) => [Number(p.lat), Number(p.lon)] as [number, number]),
    );
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 10 });
  }, [map, points]);
  return null;
}

/** Pin/cluster map of geocoded notices for one state, scoped to a time window.
 *  Auto-fits to the returned pins. Reuses /api/map-pins + the shared Leaflet
 *  setup; intentionally simpler than the global /map (no viewport paging). */
export function NoticeMap({
  state,
  after,
  before,
  height = "60vh",
}: {
  state: string;
  after?: string;
  before?: string;
  height?: string;
}) {
  const query = useQuery({
    queryKey: ["map-pins", "state", { state, after, before }],
    queryFn: () =>
      api.listMapPins({ state, after, before, limit: STATE_MAP_PIN_CAP }),
  });

  const points = query.data ?? [];

  // Memoized on `points` (referentially stable between refetches) so parent
  // re-renders don't re-reconcile thousands of <Marker> elements. Must be
  // called before the early returns below (rules of hooks).
  const markers = useMemo(
    () =>
      points.map((n) => (
        <Marker key={n.notice_id} position={[Number(n.lat), Number(n.lon)]}>
          <Popup>
            <div className="text-sm">
              <div className="font-semibold">{n.employer}</div>
              <div className="text-slate-600 dark:text-slate-400">
                {n.state} · {fmtDate(n.notice_date)}
              </div>
              <div className="mt-1">{fmtNum(n.layoff_count)} affected</div>
              <Link
                to="/notices/$noticeId"
                params={{ noticeId: n.notice_id }}
                className="mt-1 inline-block text-sky-700 hover:underline dark:text-sky-400"
              >
                Details →
              </Link>
            </div>
          </Popup>
        </Marker>
      )),
    [points],
  );

  if (query.isLoading) {
    return (
      <div className="flex items-center justify-center text-slate-500 dark:text-slate-400" style={{ height }}>
        Loading map…
      </div>
    );
  }
  if (points.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
        No geocoded notices to map for this period.
      </div>
    );
  }

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
        <MapContainer
          center={CENTER_US}
          zoom={4}
          scrollWheelZoom
          style={{ height, width: "100%", position: "relative" }}
        >
          <FitBounds points={points} />
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MarkerClusterGroup chunkedLoading>{markers}</MarkerClusterGroup>
        </MapContainer>
      </div>
      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        Showing {fmtNum(points.length)} geocoded notices.
        {points.length >= STATE_MAP_PIN_CAP && " Some pins may be omitted."}
      </div>
    </>
  );
}
