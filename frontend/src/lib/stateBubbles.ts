import type { FeatureCollection, Point } from "geojson";

import type { PlacesGeoJSON } from "../components/PlacesMap";
import { stateName } from "./format";
import { stateOf } from "./mapPlaces";

// Where each state's bubble sits: approximate geographic centers [lat, lon]
// (Michigan's on the Lower Peninsula, where its notices are). A fixed point
// per state keeps the national view stable as filters change, where a
// notice-weighted mean would wander — and could leave the state entirely.
const CENTERS: Record<string, [number, number]> = {
  AL: [32.8, -86.8], AK: [63.6, -151.5], AZ: [34.3, -111.7], AR: [34.9, -92.4],
  CA: [37.2, -119.5], CO: [39.0, -105.5], CT: [41.6, -72.7], DE: [39.0, -75.5],
  DC: [38.9, -77.0], FL: [28.4, -81.9], GA: [32.7, -83.4], HI: [20.8, -156.3],
  ID: [44.4, -114.6], IL: [40.0, -89.2], IN: [39.9, -86.3], IA: [42.1, -93.5],
  KS: [38.5, -98.4], KY: [37.5, -85.3], LA: [31.1, -92.0], ME: [45.4, -69.2],
  MD: [39.0, -76.8], MA: [42.3, -71.8], MI: [43.6, -84.7], MN: [46.3, -94.3],
  MS: [32.7, -89.7], MO: [38.4, -92.5], MT: [47.0, -109.6], NE: [41.5, -99.8],
  NV: [39.3, -116.6], NH: [43.7, -71.6], NJ: [40.2, -74.7], NM: [34.4, -106.1],
  NY: [42.9, -75.5], NC: [35.6, -79.4], ND: [47.5, -100.5], OH: [40.3, -82.8],
  OK: [35.6, -97.5], OR: [43.9, -120.6], PA: [40.9, -77.8], RI: [41.7, -71.5],
  SC: [33.9, -80.9], SD: [44.4, -100.2], TN: [35.9, -86.4], TX: [31.5, -99.3],
  UT: [39.3, -111.7], VT: [44.1, -72.7], VA: [37.5, -78.8], WA: [47.4, -120.5],
  WV: [38.6, -80.6], WI: [44.6, -89.9], WY: [43.0, -107.6], PR: [18.2, -66.5],
};

export interface StateBubbleProps {
  n: number; // notices
  w: number; // workers
  code: string;
  name: string;
  // The state's places' bounding box, for zooming in on a tap.
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
}

/** One bubble per state, summing its places — the national view, before
 *  zooming in breaks it into places. */
export function toStateBubbles(places: PlacesGeoJSON): FeatureCollection<Point, StateBubbleProps> {
  const acc = new Map<string, StateBubbleProps & { latSum: number; lonSum: number }>();
  for (const { properties: p } of places.features) {
    const code = stateOf(p.label);
    let s = acc.get(code);
    if (!s) {
      s = {
        n: 0, w: 0, code, name: stateName(code),
        min_lat: p.lat, max_lat: p.lat, min_lon: p.lon, max_lon: p.lon,
        latSum: 0, lonSum: 0,
      };
      acc.set(code, s);
    }
    s.n += p.n;
    s.w += p.w;
    s.latSum += p.lat * p.n;
    s.lonSum += p.lon * p.n;
    s.min_lat = Math.min(s.min_lat, p.lat);
    s.max_lat = Math.max(s.max_lat, p.lat);
    s.min_lon = Math.min(s.min_lon, p.lon);
    s.max_lon = Math.max(s.max_lon, p.lon);
  }
  return {
    type: "FeatureCollection",
    features: [...acc.values()].map(({ latSum, lonSum, ...props }) => {
      const [lat, lon] = CENTERS[props.code] ?? [latSum / props.n, lonSum / props.n];
      return { type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties: props };
    }),
  };
}
