/* WARN Index service worker: makes the site installable and keeps the app
   shell usable offline. Deliberately small and hand-written (no Workbox).

   - Page navigations: network first, so a deploy shows up on the next visit
     exactly as without a worker. The last good page is kept as an offline
     fallback; the SPA routes client-side, so any page works as the shell.
   - /assets/*: cache first. Vite content-hashes these names, so a cached
     copy can never be stale. Old builds are trimmed to MAX_ASSETS.
   - Everything else (the /api, feeds, embeds, OG cards, other origins) is not
     touched. API payloads are role-shaped (signed-in admins see more), so
     caching them could show one user's data to the next. */

const VERSION = "v1";
const SHELL_CACHE = `shell-${VERSION}`;
const ASSET_CACHE = `assets-${VERSION}`;
const SHELL_KEY = "/__shell";
const MAX_ASSETS = 120;

// First path segments served by FastAPI itself, not the SPA: a navigation
// there must never get the shell. Whole segments, so /feedback stays an SPA page.
const PASSTHROUGH = new Set(["api", "embed", "og", "docs", "redoc", "openapi.json", "healthz", "metrics", "feed.rss", "sitemap.xml", "sitemaps", "robots.txt"]);

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = [SHELL_CACHE, ASSET_CACHE];
      for (const key of await caches.keys()) {
        if (!keep.includes(key)) await caches.delete(key);
      }
      if (self.registration.navigationPreload) {
        await self.registration.navigationPreload.enable();
      }
      await self.clients.claim();
    })(),
  );
});

// Drop the oldest assets past MAX_ASSETS, but never one the current shell
// loads: an unchanged entry chunk can be the oldest entry and still be live.
async function trimAssets(shellHtml) {
  const live = new Set(shellHtml.match(/\/assets\/[^"'\s]+/g) || []);
  const cache = await caches.open(ASSET_CACHE);
  const stale = (await cache.keys()).filter((req) => !live.has(new URL(req.url).pathname));
  for (const req of stale.slice(0, Math.max(0, stale.length - MAX_ASSETS))) {
    await cache.delete(req); // keys() is insertion order: oldest first
  }
}

async function saveShell(response) {
  const html = await response.text();
  const cache = await caches.open(SHELL_CACHE);
  await cache.put(SHELL_KEY, new Response(html, { headers: response.headers }));
  await trimAssets(html);
}

async function handleNavigation(event) {
  try {
    const response = (await event.preloadResponse) || (await fetch(event.request));
    if (response.ok) {
      event.waitUntil(saveShell(response.clone()));
    }
    return response;
  } catch (err) {
    const shell = await caches.match(SHELL_KEY);
    if (shell) return shell;
    throw err;
  }
}

async function handleAsset(event) {
  const cached = await caches.match(event.request);
  if (cached) return cached;
  const response = await fetch(event.request);
  if (response.ok) {
    const copy = response.clone();
    event.waitUntil(caches.open(ASSET_CACHE).then((c) => c.put(event.request, copy)));
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    if (PASSTHROUGH.has(url.pathname.split("/")[1])) {
      // Still answer it, so the navigation-preload request isn't wasted.
      event.respondWith(Promise.resolve(event.preloadResponse).then((r) => r || fetch(request)));
      return;
    }
    event.respondWith(handleNavigation(event));
  } else if (url.pathname.startsWith("/assets/")) {
    event.respondWith(handleAsset(event));
  }
});
