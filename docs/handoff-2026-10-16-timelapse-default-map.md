# Hand-off: make the time-lapse the default map (2026-10-16)

`/timelapse` shipped in #379 (live on warnindex.com). Raphael's verdict: "awesome — if we can make it a little more responsive, this should be the default map view."

This note briefs the session that does both:
1. make the time-lapse faster;
2. turn it into what `/map` opens on.

Read the repo `CLAUDE.md` first. Merging to `main` is a prod deploy with no dev or QA tier.

## What exists now

| Piece | Where | Notes |
|---|---|---|
| Time-lapse page | `frontend/src/routes/timelapse.tsx` | Heat map + ranked sector race on one scrubber. URL: `bucket`, `since`, `at` (frame), `industry`. Autoplays from the window start unless `prefers-reduced-motion` is set. |
| Bar race | `frontend/src/components/IndustryRace.tsx` | Plain DOM; rows slide via CSS transforms. Tapping a sector filters the map. |
| Frame helpers | `frontend/src/lib/timelapse.ts` | Period keys, `framesGeoJSON` (one prebuilt collection per frame), `heatScaleMax` (p95 cap), `statesReporting`. |
| Map | `frontend/src/components/PlacesMap.tsx` | Shared with `/map`. `heatMax` prop. Pushes data only to the visible mode's source, so bubbles also work per frame. |
| Place timeline | `GET /api/map-places/timeline` (`warn_v2/api/routes/map_places.py`) | Groups by (4-dp point, month) in SQL and rolls up to quarter/year in Python (`warn_v2/api/timeline.py`). Sparse columnar cells. |
| Industry timeline | `GET /api/stats/industries/timeline` (`stats.py`) | Per sector per period, plus an `unclassified` row. |
| Coverage | `/api/scraper-runs/status` → `coverage_start` | `first_notice_date` minus isolated stray rows; drives "N of 48 states reporting". |
| Today's `/map` | `frontend/src/routes/map.tsx` | Full FilterBar, place search, Bubbles/Heatmap toggle, viewport in URL, `MapNoticePanel` (notices in view or at the selected place). No time dimension beyond a year slider. |

## Where the time goes (measured 2026-10-16, prod, warm, from this host)

| Request | Server time (TTFB) | gzip size |
|---|---|---|
| `map-places/timeline?bucket=quarter&after=2015-01-01` (default) | **1.65 s, on every request** | 183 KB |
| `…bucket=year&after=2015-01-01` | 1.96 s | 161 KB |
| `…bucket=month&after=1999-01-01` | **3.07 s** | 327 KB |
| `…&industry=31-33` (a linked-view tap) | 0.49 s | 48 KB |
| `stats/industries/timeline` | 0.49 s | 4 KB |
| `scraper-runs/status` | 0.29 s | 2 KB |
| `map-places` (today's `/map`) | 0.73 s | 172 KB |

- **No shared cache.** `Cache-Control: public, max-age=300` only helps one browser. Back-to-back requests both took 1.65 s, and nothing in front of the API (DO nginx, Traefik) caches. There is one API replica (`api.replicas: 1`).
- **It's the SQL.** Locally, against a SQLite copy of prod data, the endpoint spent 0.47 s of 0.56 s in the query and 0.10 s in Python/JSON. The query groups ~79k geocoded notices by `round(lat,4), round(lon,4), substr(notice_date,1,7)`. Year and quarter are no cheaper, because SQL always groups by month.
- **Every bucket or window switch is a cold fetch.** The map goes blank for 1.6–3 s on purpose: the stale payload's period keys don't match the new frames (#379 review fix).
- **Frame stepping is already cheap.** In headless Chromium at 390×844, CPU throttled 4× (verified), on SwiftShader WebGL:
  - one scrub step costs ~30 ms of main thread (p95 36 ms, monthly since 1999), measured from input to two rAFs later;
  - autoplay showed 0 long tasks and an rAF p95 of 16.7 ms.

  What was **not** measured: input → heat layer repainted. `setData` parses in the worker, so the paint can lag the scrubber. Measure that before optimizing frames (see below).
- **First paint stacks up.** In order: the lazy MapLibre chunk (`PlacesMap-*.js`, 289 KB gz) → map init → the 1.65 s timeline query → the heat layer. `/map` today needs only the 0.73 s `map-places` query.

So "a little more responsive" is mostly a **server** problem (seconds), then a **switching** problem (refetch per bucket/window), and only last a frame-rate problem (milliseconds).

## Recommended build

### 1. Make the timeline fast (backend, do this first, ship on its own)

- **Cache the timeline response bodies in-process with a TTL.** Key on the full normalized query (bucket, after, before, state, closure, industry, subsector). The data changes only when scrapers land, a few times a day.
  - The repo already has two patterns: `logo_fetch._TTLCache` (thread-safe LRU with expiry) and `og.py`'s `_cache` + `_lock`. Reuse one; don't add a dependency.
  - Cache the **serialized** body (bytes), so a hit skips both the SQL and JSON encoding.
  - It's per process. Check how many uvicorn workers the API runs (Dockerfile / chart command) before trusting the hit rate.
- **Warm the default views** in a background thread after startup and on expiry. Otherwise the first visitor after each TTL pays 1.6–3 s. The default is quarterly since 2015, plus whatever the new `/map` opens on.
- **Group once, roll up many.** Quarter and year can be derived from the cached **month** grouping (Python roll-up is ~0.1 s), so cache the monthly rows per filter set, not one entry per bucket.
- Only if the cold path still matters after caching: try an expression index or a materialized monthly (point, month) table refreshed after scrapes. Measure with `EXPLAIN ANALYZE` on prod's shape first. Locally it's SQLite, not representative.
- Success: warm TTFB < 150 ms for the default and the monthly-since-1999 view (`curl -w %{time_starttransfer}` against prod after deploy). Tests: a cache hit returns identical JSON; a different filter misses; expiry refetches.

### 2. Make switching instant (frontend)

- **Fetch the monthly payload once per filter set and roll it up on the client** to quarter/year. `periodOf` in `lib/timelapse.ts` already mirrors the server roll-up. Bucket switches then need no request.
  - Monthly since 1999 is 327 KB gz, so don't block first paint on it. Show the default quarterly payload first, then prefetch monthly in the background (react-query `prefetchQuery`) and switch to client-side roll-ups once it lands.
  - Window changes (`since`) then only change which frames are shown, not what is loaded: fetch from 1999 once and slice.
- **Linked-view taps** (0.49 s): prefetch the top few sectors of the current frame on idle, or accept the latency but keep the old frames up meanwhile (`keepPreviousData` is still correct here, because only the industry changes).
- **Measure frame latency properly**, then decide on `setFilter`. Record time from the scrub `input` event to the map's next `idle` (or a `sourcedata` with `isSourceLoaded`) under 4× throttle, at month granularity.
  - If it's > ~100 ms, try one GeoJSON source holding every cell with a `p` (frame index) property and `map.setFilter("heat", ["==", ["get", "p"], frame])`. That needs no worker re-parse per frame, but it's a bigger source. #379 found `setData` fast on the main thread, but never measured the paint.
- **Partial current period:** today it's labelled "partial". If it's the frame `/map` opens on, show its `projected_*` pace like the other charts, or open on the last complete period (see the open questions).

### 3. Fold it into `/map`

`/map` has features the time-lapse lacks, and the default view can't lose them:
- FilterBar: state, closure type, industry/subsector, min workers, dates;
- place search;
- the notice panel;
- Bubbles mode;
- viewport in the URL;
- the "N notices · N workers ↓" chip on phones.

Suggested shape:
- **Time becomes a control on `/map`, not a separate page.** The timeline card (frame strip + scrubber + play) sits above the map. "All time" is the aggregate view `/map` shows today; scrubbing or playing selects a period.
  - The year slider and `after/before` filters fold into the scrubber's window.
- **The notice panel follows the frame.** Pass the period's bounds as `after`/`before` into `MapNoticePanel`'s `filters` while a frame is selected. It already takes `filters` + `bounds` + `selected`.
- **Bubbles per frame work today.** `PlacesMap` pushes to the clustered source in bubbles mode, so keep the Bubbles/Heatmap toggle.
- **Industry race placement.** `/map`'s right column is the notice panel. Options: tabs in that column (Notices | Industries); the race under the map; or race-as-filter only on desktop. Ask Raphael.
- **`/timelapse` redirects** to `/map` with the equivalent params, so links from #379 (dashboard, /map header) and shared URLs keep working. Remove the then-circular "Watch it over time" link on `/map`.
- **Bundle:** `/map` already lazy-loads MapLibre; the race and timeline helpers are ~6 KB gz. No new split needed.

## Non-negotiables (carried over from #379)

- **Coverage honesty.** The states-reporting count and hatched inset stay on the graphic in every frame. The "Industry known for N%" line and the Unclassified row stay.
- **`prefers-reduced-motion`:** no autoplay, no bar transitions. If `/map` becomes the default, **autoplay on every `/map` visit is probably wrong for everyone**: people come to `/map` to look something up. Recommend opening paused (see Q1).
- **Accessibility:**
  - the scrubber stays a labelled `input[type=range]` with `aria-valuetext`;
  - the live region is silent while playing;
  - rank is exposed to screen readers;
  - the table equivalent stays.
- **Mobile first:** verify on a throttled 390×844 profile, both themes.
- **No regression for existing `/map` links:** `?lat/lon/zoom`, `?mode=heat`, filter params, and old `?after/before` year selections must still open the same view.
- **Strategic-merge caution** only applies if the chart changes. This plan shouldn't touch `charts/`.

## Verification recipe

The real-data recipe from #379's session; scripts weren't committed, so recreate them:

1. **Fetch prod notices.** Page `https://warnindex.com/api/notices?limit=500&offset=N` at 1 req/s into JSONL, deduped by `notice_id`.
   - It took **~10 minutes** for 86k notices, not 3, because each page takes a few seconds. Run it in the background. Skip `geocoded_only` so the industry race has every notice.
2. **Build a scratch SQLite DB.** `Base.metadata.create_all`, then insert `Company(id, name, naics_code, website)`, `Location(id, city, county, state, zip, lat, lon)`, `Notice(...)`, and one `ScraperRun(status="ok")` per state so `/scraper-runs/status` has rows.
   - Run with `python -c "exec(open(...).read())"` and the worktree as cwd, and print `warn_v2.__file__` to confirm (`CLAUDE.md`'s venv-shadowing note).
3. **Serve it.** `uvicorn warn_v2.api:app --port 8010` with `DATABASE_URL=sqlite:///…` and `RATE_ANON_PER_MIN=100000`.
   - **Port 8000 may belong to another session's uvicorn:** check `Get-NetTCPConnection -LocalPort 8000` and don't kill it.
   - Serve the **production bundle**: `npm run build`, then `API_PROXY_TARGET=http://localhost:8010 npx vite preview --port 4173` (`preview.proxy` inherits `server.proxy`). The dev server isn't representative for performance.
4. **Measure with Playwright** from the double-p venv (`C:\Users\rapha\workspace\warn_scrapper_v2\.venv`):
   - setup: 390×844, `is_mobile`, CDP `Emulation.setCPUThrottlingRate` 4, launch args `--use-angle=swiftshader --enable-unsafe-swiftshader`;
   - confirm the throttle took (a fixed busy loop should take ~4× longer);
   - record rAF deltas and `longtask` entries while playing;
   - record scrub input → map `idle` latency;
   - take screenshots in both themes.
5. **Measure the backend against prod** (warm and cold) with `curl -w "%{time_starttransfer}"` before and after the deploy. The numbers in the table above are the baseline.

Gotchas:
- After `kill`/`Stop-Process` of a background server, its task reports exit 127/1. That's expected.
- `npm ci` in a fresh worktree is needed before `tsc`/`lint`; don't commit `frontend/tsconfig.tsbuildinfo`.
- This session's own worktree folder was emptied mid-session (cleanup). Git commands then silently fell through to the shared main checkout one level up. If `ls` in your worktree is empty, stop and make a fresh private worktree; don't commit from the main checkout.

## Open questions for Raphael (ask before building parts 2–3)

1. **What `/map` opens on:** paused on the last complete period (recommended), the all-time aggregate (today's view), or autoplay?
2. **Industry race on `/map`:** a tab beside the notice panel (recommended), under the map, or dropped from `/map` (kept on `/timelapse`)?
3. **Default bucket/window on `/map`:** keep quarterly since 2015, or monthly since there's now no fetch per switch?
4. **`/timelapse`:** redirect to `/map` (recommended), or keep it as a separate "presentation" page that autoplays?
5. **Part 1 first as its own PR?** Recommended: it's backend-only, low risk, and makes the current `/timelapse` feel faster immediately.
