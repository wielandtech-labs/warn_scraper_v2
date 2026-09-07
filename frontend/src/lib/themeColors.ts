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
}

export const CHART_COLORS: Record<ResolvedTheme, ChartColors> = {
  light: {
    grid: "#e2e8f0", // slate-200
    axis: "#64748b", // slate-500
    notices: "#0369a1", // sky-700
    layoffs: "#dc2626", // red-600
    cursor: "rgba(203, 213, 225, 0.4)", // BarChart hover band; default #ccc
    tooltip: {
      backgroundColor: "#ffffff",
      border: "1px solid #e2e8f0",
      color: "#0f172a",
    },
    tooltipLabel: { color: "#0f172a" },
  },
  dark: {
    grid: "#334155", // slate-700
    axis: "#94a3b8", // slate-400
    notices: "#38bdf8", // sky-400 — same hue, brighter for dark backgrounds
    layoffs: "#f87171", // red-400
    cursor: "rgba(148, 163, 184, 0.15)",
    tooltip: {
      backgroundColor: "#1e293b",
      border: "1px solid #334155",
      color: "#f1f5f9",
    },
    tooltipLabel: { color: "#f1f5f9" },
  },
};

interface UsMapColors {
  /* Fill for states absent from a UsMap's fills record. */
  noData: string;
  stateStroke: string;
  hoverStroke: string;
  connector: string;
}

/* Scaffolding colors shared by every UsMap-based map (strokes, DC callout
   connector); the per-state fills are each map's own concern. */
export const US_MAP: Record<ResolvedTheme, UsMapColors> = {
  light: {
    noData: "#f1f5f9",
    stateStroke: "#fff",
    hoverStroke: "#0f172a",
    connector: "#94a3b8",
  },
  dark: {
    noData: "#1e293b",
    stateStroke: "#020617",
    hoverStroke: "#f8fafc",
    connector: "#64748b",
  },
};

interface ChoroplethColors {
  /* Zero bucket + four quartile buckets. On dark backgrounds lighter =
     more salient, so the ramp direction inverts: severity brightens. */
  buckets: [string, string, string, string, string];
}

export const CHOROPLETH: Record<ResolvedTheme, ChoroplethColors> = {
  light: {
    buckets: ["#f1f5f9", "#bae6fd", "#7dd3fc", "#0ea5e9", "#0369a1"],
  },
  dark: {
    buckets: ["#1e293b", "#0c4a6e", "#0369a1", "#0ea5e9", "#7dd3fc"],
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
