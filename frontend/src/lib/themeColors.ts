import type { CSSProperties } from "react";

import type { ResolvedTheme } from "../hooks/useTheme";

/* All non-Tailwind color tokens, keyed by resolved theme. Anything rendered
   from JS (Recharts props, choropleth SVG fills, Leaflet tile URLs) reads
   from here so a theme toggle re-renders it; CSS-driven color lives in
   Tailwind dark: variants instead. */

interface ChartColors {
  grid: string;
  axis: string;
  notices: string;
  layoffs: string;
  cursor: string;
  tooltip: CSSProperties;
  tooltipLabel: CSSProperties;
  /* Categorical series for the BLS indicator cards, assigned in this fixed
     order within each card (never cycled, never reassigned when a series
     drops out). Deliberately NOT the notices/layoffs hues: a BLS series
     measures something different from a WARN count, and sharing a color
     would imply they are the same quantity.

     Validated with the dataviz palette checker (--pairs all) at both chart
     surfaces. Amber sits close to the layoffs red for deuteranopes, so it
     must never share a chart with layoffs. */
  indicators: [string, string, string];
  /* The one BLS series drawn against WARN in WarnTimeChart's Compare mode.
     Validated as a pair with `layoffs` in both modes (and it is not amber). */
  context: string;
  /* Recession shading behind the series. */
  annotation: string;
}

export const CHART_COLORS: Record<ResolvedTheme, ChartColors> = {
  light: {
    grid: "#e1e0d9",
    axis: "#6e6c66",
    notices: "#2a78d6",
    layoffs: "#DA2F25", // brand red
    cursor: "rgba(195, 194, 183, 0.35)", // BarChart hover band; default #ccc
    tooltip: {
      backgroundColor: "#fcfcfb",
      border: "1px solid #e1e0d9",
      color: "#1a1a19",
    },
    tooltipLabel: { color: "#1a1a19" },
    indicators: ["#0f8a60", "#b37800", "#4a3aa7"], // aqua, amber, violet
    context: "#4a3aa7",
    annotation: "rgba(110, 108, 102, 0.10)",
  },
  dark: {
    grid: "#2c2c2a",
    axis: "#a3a199",
    notices: "#3987e5", // same hue, brighter for dark backgrounds
    layoffs: "#e66767",
    cursor: "rgba(163, 161, 153, 0.15)",
    tooltip: {
      backgroundColor: "#2c2c2a",
      border: "1px solid #3d3c39",
      color: "#f9f9f7",
    },
    tooltipLabel: { color: "#f9f9f7" },
    indicators: ["#199e70", "#c98500", "#9085e9"],
    context: "#9085e9",
    annotation: "rgba(163, 161, 153, 0.10)",
  },
};

interface UsMapColors {
  /* Fill for states absent from a UsMap's fills record. */
  noData: string;
  stateStroke: string;
  hoverStroke: string;
  /* Fill for the state under the pointer on maps whose base fill is uniform
     (HeroMap). Distinct from noData in both themes. */
  hoverFill: string;
  connector: string;
}

/* Scaffolding colors shared by every UsMap-based map (strokes, DC callout
   connector); the per-state fills are each map's own concern. */
export const US_MAP: Record<ResolvedTheme, UsMapColors> = {
  light: {
    noData: "#f0efec",
    stateStroke: "#fff",
    hoverStroke: "#1a1a19",
    hoverFill: "#e1e0d9",
    connector: "#a3a199",
  },
  dark: {
    noData: "#2c2c2a",
    stateStroke: "#0d0d0d",
    hoverStroke: "#f9f9f7",
    hoverFill: "#3d3c39",
    connector: "#6e6c66",
  },
};

interface ChoroplethColors {
  /* Zero bucket + four quartile buckets. On dark backgrounds lighter =
     more salient, so the ramp direction inverts: severity brightens. */
  buckets: [string, string, string, string, string];
}

export const CHOROPLETH: Record<ResolvedTheme, ChoroplethColors> = {
  light: {
    buckets: ["#f0efec", "#b7d3f6", "#6da7ec", "#2a78d6", "#104281"],
  },
  dark: {
    buckets: ["#2c2c2a", "#184f95", "#256abf", "#5598e7", "#9ec5f4"],
  },
};

export const TILE_LAYERS: Record<
  ResolvedTheme,
  { url: string; attribution: string }
> = {
  light: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  dark: {
    // CARTO raster basemap: free for non-commercial use with attribution.
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=cb1_2sq1_1_a51e5819cc710c716cb3ff00",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  },
};
