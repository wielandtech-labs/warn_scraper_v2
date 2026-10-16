import type { MapPlaces } from "../api/client";
import type { PlacesGeoJSON, View } from "../components/PlacesMap";

/** /api/map-places' parallel arrays as the GeoJSON PlacesMap renders. */
export function toGeoJSON(p: MapPlaces): PlacesGeoJSON {
  return {
    type: "FeatureCollection",
    features: p.lat.map((lat, i) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lon[i], lat] },
      properties: { n: p.notices[i], w: p.workers[i], label: p.label[i], lat, lon: p.lon[i] },
    })),
  };
}

export const EMPTY_PLACES: PlacesGeoJSON = { type: "FeatureCollection", features: [] };

/** State code of a place label ("City, ST" or "ST"). */
export const stateOf = (label: string) => label.slice(-2);

/** Bounding box of the places that pass `keep` (all by default); null if none do. */
export function placesBounds(
  p: MapPlaces,
  keep: (i: number) => boolean = () => true,
): View["bounds"] | null {
  let b: View["bounds"] | null = null;
  for (let i = 0; i < p.lat.length; i++) {
    if (!keep(i)) continue;
    const lat = p.lat[i];
    const lon = p.lon[i];
    b = b
      ? {
          min_lat: Math.min(b.min_lat, lat),
          max_lat: Math.max(b.max_lat, lat),
          min_lon: Math.min(b.min_lon, lon),
          max_lon: Math.max(b.max_lon, lon),
        }
      : { min_lat: lat, max_lat: lat, min_lon: lon, max_lon: lon };
  }
  return b;
}
