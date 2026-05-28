import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend paths that should be proxied to the FastAPI dev server during
// `npm run dev`. In prod, the SPA is served by the same FastAPI process
// (via StaticFiles), so no proxy is needed.
const API_PATHS = [
  "/notices",
  "/companies",
  "/scraper-runs",
  "/stats",
  "/healthz",
  "/metrics",
  "/docs",
  "/openapi.json",
];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((p) => [p, { target: "http://localhost:8000", changeOrigin: true }]),
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
