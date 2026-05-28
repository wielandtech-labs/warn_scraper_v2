import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import L from "leaflet";
import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
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

export function MapPage() {
  const navigate = useNavigate({ from: "/map" });
  const search = useSearch({ from: "/map" });

  // Pull a large batch — the map needs as many as the API will give us.
  const query = useQuery({
    queryKey: ["map", search],
    queryFn: () =>
      api.listNotices({
        state: search.state,
        after: search.after,
        before: search.before,
        limit: 500,
      }),
  });

  const handleFilterChange = (next: FilterValues) => {
    navigate({ search: () => ({ ...next, employer: undefined }) });
  };

  const points =
    query.data?.items.filter(
      (n) => n.location?.lat != null && n.location?.lon != null,
    ) ?? [];

  return (
    <div>
      <h1 className="mb-3 text-2xl font-semibold">Map</h1>
      <FilterBar values={search} onChange={handleFilterChange} showEmployer={false} />

      <div className="overflow-hidden rounded-lg border border-slate-200">
        <MapContainer
          center={CENTER_US}
          zoom={4}
          scrollWheelZoom
          style={{ height: "70vh", width: "100%", position: "relative" }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MarkerClusterGroup chunkedLoading>
            {points.map((n) => (
              <Marker
                key={n.notice_id}
                position={[Number(n.location!.lat), Number(n.location!.lon)]}
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
        Showing {points.length} geocoded of {query.data?.items.length ?? 0} fetched
        {" "}(of {fmtNum(query.data?.total ?? 0)} total notices).
      </div>
    </div>
  );
}
