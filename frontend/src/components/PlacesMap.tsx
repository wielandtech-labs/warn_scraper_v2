import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import {
  GeolocateControl,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
  type ExpressionSpecification,
  type GeoJSONSource,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection, Point } from "geojson";
// MapLibre locates its worker relative to its own module URL, which doesn't
// survive Vite's dependency pre-bundling or the production chunking. Bundling
// the worker as its own asset and pointing MapLibre at it works in both.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

import type { ResolvedTheme } from "../hooks/useTheme";
import { CHART_COLORS, HEAT_STOPS, TILE_LAYERS } from "../lib/themeColors";

setWorkerUrl(workerUrl);

/* GPU-rendered, worker-clustered map of geocoded places for /map.

   Every place in the filtered set is loaded at once (the API aggregates
   notices per point, so ~80k notices are ~15k features) and MapLibre
   clusters them off the main thread — nothing here scales with the number
   of notices, which is what makes it usable on a phone. The component is
   imperative inside one long-lived map instance: props are pushed into it by
   effects rather than re-creating anything on render. */

export interface PlaceProps {
  n: number; // notices
  w: number; // workers (reported layoff counts)
  label: string;
  // Exact coordinates. A rendered feature's geometry is quantized to its
  // vector tile's grid, too coarse to identify the place it came from.
  lat: number;
  lon: number;
}
export type PlacesGeoJSON = FeatureCollection<Point, PlaceProps>;

export type MapMode = "bubbles" | "heat";

export interface View {
  lat: number;
  lon: number;
  zoom: number;
  bounds: { min_lat: number; min_lon: number; max_lat: number; max_lon: number };
}

export type SelectedPlace = PlaceProps;

export interface PlacesMapHandle {
  flyTo: (lat: number, lon: number, zoom: number) => void;
  fitBounds: (b: View["bounds"]) => void;
}

// Bold digits for the cluster labels. Only the 0-255 range is ever fetched
// (digits, "k", ","), ~80 KB once per visit.
const GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
const FONT = ["Noto Sans Bold"];

// First-visit framing when the URL carries no view: the contiguous US.
const CONUS: [[number, number], [number, number]] = [
  [-124.8, 24.5],
  [-66.9, 49.4],
];

// How a box of places is framed: room for the bubbles at the edges, and no
// closer than a metro area when the box is one point.
const FIT = { padding: 40, maxZoom: 9 };
const toLngLatBounds = (b: View["bounds"]): [[number, number], [number, number]] => [
  [b.min_lon, b.min_lat],
  [b.max_lon, b.max_lat],
];

const EMPTY: PlacesGeoJSON = { type: "FeatureCollection", features: [] };
const BUBBLE_LAYERS = ["clusters", "points", "counts"];
const HEAT_LAYERS = ["heat", "heat-points"];

// Area-true sizing: radius grows with sqrt(workers), clamped at both ends so a
// place with no reported count stays tappable and a metro cluster stays sane.
const sqrtW: ExpressionSpecification = ["sqrt", ["get", "w"]];
const CLUSTER_RADIUS: ExpressionSpecification = [
  "interpolate", ["linear"], sqrtW, 0, 12, 100, 20, 400, 34, 1000, 44,
];
const POINT_RADIUS: ExpressionSpecification = [
  "interpolate", ["linear"], sqrtW, 0, 5, 10, 8, 40, 14, 120, 24,
];
// Notice count, abbreviated past 1,000 ("12.3k").
const COUNT_LABEL: ExpressionSpecification = [
  "case",
  [">=", ["get", "n"], 1000],
  ["concat", ["to-string", ["/", ["round", ["/", ["get", "n"], 100]], 10]], "k"],
  ["to-string", ["get", "n"]],
];

function baseSourceId(theme: ResolvedTheme) {
  return `base-${theme}`;
}

/** Raster source for the theme's tile layer: the URLs' `{s}` subdomain and
 *  `{r}` retina placeholders aren't MapLibre syntax, so expand them. */
function baseSource(theme: ResolvedTheme) {
  const { url, attribution } = TILE_LAYERS[theme];
  const urls = url.includes("{s}") ? ["a", "b", "c"].map((s) => url.replace("{s}", s)) : [url];
  return {
    type: "raster" as const,
    tiles: urls.map((u) => u.replace("{r}", "")),
    tileSize: 256,
    maxzoom: 19,
    attribution,
  };
}

function initialStyle(theme: ResolvedTheme): StyleSpecification {
  return {
    version: 8,
    glyphs: GLYPHS,
    sources: { [baseSourceId(theme)]: baseSource(theme) },
    layers: [{ id: "base", type: "raster", source: baseSourceId(theme) }],
  };
}

// A place's heat weight ramps up to full at `max` workers (fixed, so frames of
// a time-lapse share one scale) from a floor that keeps count-less places warm.
const heatWeight = (max: number): ExpressionSpecification => [
  "interpolate", ["linear"], ["get", "w"], 0, 0.15, max, 1,
];
const DEFAULT_HEAT_MAX = 500;

function addDataLayers(map: MapLibreMap, theme: ResolvedTheme) {
  const red = CHART_COLORS[theme].layoffs;
  const halo = theme === "dark" ? "#0d0d0d" : "#ffffff";

  map.addSource("places", {
    type: "geojson",
    data: EMPTY,
    cluster: true,
    clusterRadius: 50,
    clusterMaxZoom: 11,
    // Clusters carry the summed notice + worker counts of their places.
    clusterProperties: { n: ["+", ["get", "n"]], w: ["+", ["get", "w"]] },
  });
  // The heat layer reads unclustered places: weighting by cluster sums would
  // make hot spots jump as clusters regroup on zoom.
  map.addSource("places-raw", { type: "geojson", data: EMPTY });
  map.addSource("selected", { type: "geojson", data: EMPTY });

  map.addLayer({
    id: "clusters",
    type: "circle",
    source: "places",
    filter: ["has", "point_count"],
    paint: {
      "circle-color": red,
      "circle-opacity": 0.78,
      "circle-radius": CLUSTER_RADIUS,
      "circle-stroke-color": halo,
      "circle-stroke-width": 1.5,
    },
  });
  map.addLayer({
    id: "points",
    type: "circle",
    source: "places",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": red,
      "circle-opacity": 0.85,
      "circle-radius": POINT_RADIUS,
      "circle-stroke-color": halo,
      "circle-stroke-width": 1.5,
    },
  });
  map.addLayer({
    id: "counts",
    type: "symbol",
    source: "places",
    filter: [">", ["get", "n"], 1],
    layout: {
      "text-field": COUNT_LABEL,
      "text-font": FONT,
      "text-size": 11,
      "text-allow-overlap": true,
    },
    paint: { "text-color": "#ffffff" },
  });
  map.addLayer({
    id: "heat",
    type: "heatmap",
    source: "places-raw",
    layout: { visibility: "none" },
    paint: {
      "heatmap-weight": heatWeight(DEFAULT_HEAT_MAX),
      "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 3, 0.6, 10, 2.5],
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 3, 8, 10, 24],
      "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 10, 0.85, 13, 0.25],
      "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], ...HEAT_STOPS.flat()],
    },
  });
  // Close in, heat alone gives nothing to tap — fade real places in.
  map.addLayer({
    id: "heat-points",
    type: "circle",
    source: "places-raw",
    minzoom: 9,
    layout: { visibility: "none" },
    paint: {
      "circle-color": red,
      "circle-radius": POINT_RADIUS,
      "circle-opacity": ["interpolate", ["linear"], ["zoom"], 9, 0, 11, 0.85],
      "circle-stroke-color": halo,
      "circle-stroke-width": 1,
    },
  });
  map.addLayer({
    id: "selected",
    type: "circle",
    source: "selected",
    paint: {
      "circle-color": "rgba(0,0,0,0)",
      "circle-radius": ["+", POINT_RADIUS, 5],
      "circle-stroke-color": theme === "dark" ? "#f9f9f7" : "#1a1a19",
      "circle-stroke-width": 2.5,
    },
  });
}

function toView(map: MapLibreMap): View {
  const c = map.getCenter();
  const b = map.getBounds();
  const r = (n: number) => Math.round(n * 1e4) / 1e4;
  return {
    lat: r(c.lat),
    lon: r(c.lng),
    zoom: Math.round(map.getZoom() * 100) / 100,
    bounds: {
      min_lat: r(b.getSouth()),
      min_lon: r(b.getWest()),
      max_lat: r(b.getNorth()),
      max_lon: r(b.getEast()),
    },
  };
}

export const PlacesMap = forwardRef<
  PlacesMapHandle,
  {
    data: PlacesGeoJSON;
    mode: MapMode;
    theme: ResolvedTheme;
    /** Starting view: a center + zoom, a box to fit, or null for the
     *  contiguous US. Read once, at mount. */
    initial: { lat: number; lon: number; zoom: number } | { bounds: View["bounds"] } | null;
    selected: SelectedPlace | null;
    /** Workers at which a place's heat saturates (default 500). */
    heatMax?: number;
    onViewChange: (v: View) => void;
    onSelect: (p: SelectedPlace | null) => void;
    className?: string;
  }
>(function PlacesMap(
  {
    data,
    mode,
    theme,
    initial,
    selected,
    heatMax = DEFAULT_HEAT_MAX,
    onViewChange,
    onSelect,
    className,
  },
  ref,
) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  // Latest props for the long-lived map's event handlers and load callback.
  const latest = useRef({ data, mode, theme, selected, heatMax, onViewChange, onSelect });
  latest.current = { data, mode, theme, selected, heatMax, onViewChange, onSelect };
  const loaded = useRef(false);
  const themeRef = useRef(theme); // the theme the base layer currently shows

  useImperativeHandle(ref, () => ({
    flyTo: (lat, lon, zoom) => mapRef.current?.flyTo({ center: [lon, lat], zoom, essential: true }),
    fitBounds: (b) => mapRef.current?.fitBounds(toLngLatBounds(b), FIT),
  }));

  // Create the map once. Everything else is pushed in by the effects below.
  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current!,
      style: initialStyle(theme),
      ...(initial === null
        ? { bounds: CONUS, fitBoundsOptions: { padding: 8 } }
        : "bounds" in initial
          ? { bounds: toLngLatBounds(initial.bounds), fitBoundsOptions: FIT }
          : { center: [initial.lon, initial.lat] as [number, number], zoom: initial.zoom }),
      minZoom: 2,
      maxZoom: 17,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      attributionControl: { compact: true },
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.addControl(
      new GeolocateControl({
        positionOptions: { enableHighAccuracy: false, timeout: 10_000 },
        fitBoundsOptions: { maxZoom: 9 },
      }),
      "top-right",
    );
    mapRef.current = map;

    map.on("load", () => {
      addDataLayers(map, themeRef.current);
      loaded.current = true;
      const { data, mode, selected, theme, heatMax } = latest.current;
      if (theme !== themeRef.current) {
        pushTheme(map, themeRef.current, theme); // toggled before the map loaded
        themeRef.current = theme;
      }
      pushData(map, data, mode);
      pushMode(map, mode);
      pushSelected(map, selected);
      if (heatMax !== DEFAULT_HEAT_MAX) map.setPaintProperty("heat", "heatmap-weight", heatWeight(heatMax));
      latest.current.onViewChange(toView(map));
    });
    map.on("moveend", () => latest.current.onViewChange(toView(map)));

    map.on("click", "clusters", async (e: MapLayerMouseEvent) => {
      const f = e.features?.[0];
      if (!f) return;
      const src = map.getSource("places") as GeoJSONSource;
      try {
        const zoom = await src.getClusterExpansionZoom(f.properties.cluster_id as number);
        map.easeTo({ center: (f.geometry as Point).coordinates as [number, number], zoom });
      } catch {
        // The data was replaced mid-tap and the cluster id is stale; the tap is moot.
      }
    });
    const selectPoint = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as PlaceProps;
      latest.current.onSelect({ lat: p.lat, lon: p.lon, n: p.n, w: p.w, label: p.label });
    };
    map.on("click", "points", selectPoint);
    map.on("click", "heat-points", selectPoint);
    // A tap on empty map clears the selection (feature clicks fire first and
    // are recognised by the rendered-feature query).
    map.on("click", (e) => {
      const hits = map.queryRenderedFeatures(e.point, {
        layers: ["clusters", "points", "heat-points"].filter((l) => map.getLayer(l)),
      });
      if (hits.length === 0) latest.current.onSelect(null);
    });
    for (const layer of ["clusters", "points", "heat-points"]) {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }

    return () => {
      loaded.current = false;
      map.remove();
      mapRef.current = null;
    };
    // Mount-only: the initial view and theme seed the map; later changes are
    // pushed by the effects below (or by the user moving the map).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (mapRef.current && loaded.current) pushData(mapRef.current, data, latest.current.mode);
  }, [data]);

  useEffect(() => {
    if (!mapRef.current || !loaded.current) return;
    pushData(mapRef.current, latest.current.data, mode);
    pushMode(mapRef.current, mode);
  }, [mode]);

  useEffect(() => {
    if (mapRef.current && loaded.current) pushSelected(mapRef.current, selected);
  }, [selected]);

  useEffect(() => {
    if (mapRef.current && loaded.current)
      mapRef.current.setPaintProperty("heat", "heatmap-weight", heatWeight(heatMax));
  }, [heatMax]);

  // Before load, the load handler applies the latest theme. (Not
  // isStyleLoaded(): it also reads false while a source re-tiles after
  // setData, and "load" never fires again to retry.)
  useEffect(() => {
    if (!mapRef.current || !loaded.current || themeRef.current === theme) return;
    pushTheme(mapRef.current, themeRef.current, theme);
    themeRef.current = theme;
  }, [theme]);

  return <div ref={container} className={className} />;
});

/** Swap the raster source under the data layers and recolor strokes, rather
 *  than setStyle(), which would drop the data sources and re-cluster. */
function pushTheme(map: MapLibreMap, from: ResolvedTheme, to: ResolvedTheme) {
  map.removeLayer("base");
  map.removeSource(baseSourceId(from));
  map.addSource(baseSourceId(to), baseSource(to));
  map.addLayer({ id: "base", type: "raster", source: baseSourceId(to) }, "clusters");
  const red = CHART_COLORS[to].layoffs;
  const halo = to === "dark" ? "#0d0d0d" : "#ffffff";
  for (const l of ["clusters", "points", "heat-points"]) {
    map.setPaintProperty(l, "circle-color", red);
    map.setPaintProperty(l, "circle-stroke-color", halo);
  }
  map.setPaintProperty("selected", "circle-stroke-color", to === "dark" ? "#f9f9f7" : "#1a1a19");
}

/** Only the shown mode's source gets the data: re-clustering hidden bubbles
 *  on every update (each frame of a time-lapse) would be wasted work. */
function pushData(map: MapLibreMap, data: PlacesGeoJSON, mode: MapMode) {
  (map.getSource("places") as GeoJSONSource).setData(mode === "bubbles" ? data : EMPTY);
  (map.getSource("places-raw") as GeoJSONSource).setData(mode === "heat" ? data : EMPTY);
}

function pushMode(map: MapLibreMap, mode: MapMode) {
  for (const l of BUBBLE_LAYERS) map.setLayoutProperty(l, "visibility", mode === "bubbles" ? "visible" : "none");
  for (const l of HEAT_LAYERS) map.setLayoutProperty(l, "visibility", mode === "heat" ? "visible" : "none");
}

function pushSelected(map: MapLibreMap, p: SelectedPlace | null) {
  (map.getSource("selected") as GeoJSONSource).setData(
    p
      ? {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Point", coordinates: [p.lon, p.lat] },
              properties: p,
            },
          ],
        }
      : EMPTY,
  );
}
