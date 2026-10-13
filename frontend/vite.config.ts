import process from "node:process";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend paths that should be proxied to the FastAPI dev server during
// `npm run dev`. In prod, the SPA is served by the same FastAPI process
// (via StaticFiles), so no proxy is needed.
// All domain API routes live under /api to avoid shadowing SPA paths.
const API_PATHS = [
  "/api",
  "/healthz",
  "/metrics",
  "/docs",
  "/openapi.json",
];

// Point the dev proxy at another backend, e.g. the public site, to preview UI
// changes against real data without a local DB:
//   API_PROXY_TARGET=https://warnindex.com npm run dev
const API_TARGET = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((p) => [p, { target: API_TARGET, changeOrigin: true }]),
    ),
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    // Increase chunk size warning threshold — Leaflet + Recharts together
    // push us slightly over the default 500 KB.
    chunkSizeWarningLimit: 1000,
  },
});
