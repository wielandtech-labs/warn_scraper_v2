# Time-lapse graphics hand-off — 2026-10-16

The point of WARN Index is to show **where** layoffs happen, **when**, and **in which industry**. The new `/map` (#373, #375) answers "where", and its heatmap mode landed especially well. This note briefs a new session to build two **time-lapse** graphics that add the "when":

1. **Geographic time-lapse:** a map that plays through time, showing where layoffs concentrate in each period.
2. **Industry time-lapse:** the same timeline, showing which sectors are shedding jobs in each period.

Read the repo `CLAUDE.md` first. Merging to `main` is a prod deploy, with no dev or QA tier.

## What already exists (reuse it)

| Piece | Where | Notes |
|---|---|---|
| MapLibre map with bubbles + heatmap | `frontend/src/components/PlacesMap.tsx` | Imperative, long-lived map; props are pushed in by effects. The heatmap is the `heat` layer on the unclustered `places-raw` source, weighted by workers. Theme swap: `pushTheme()`. Lazy-load pattern: `NoticeMap.tsx` (#375). |
| Per-place aggregate | `GET /api/map-places` (`warn_v2/api/routes/map_places.py`) | Groups by 4-dp point and returns columnar `{lat, lon, notices, workers, label}`. Takes the standard filters. No time dimension. |
| Place → GeoJSON helpers | `frontend/src/lib/mapPlaces.ts` | `toGeoJSON`, `placesBounds`, `stateOf`. |
| Time series | `GET /api/stats/over-time?bucket=day\|month\|year` | Takes state / industry / subsector / closure / date filters. Includes `projected_*` for the partial current period. |
| Per state | `GET /api/stats/by-state` | Counts and workers per state for a date range. One call per frame would be wasteful; see below. |
| Industry totals | `GET /api/stats/industries` | NAICS sectors (+ subsectors), all time only. |
| Coverage per state | `GET /api/scraper-runs/status` | Returns `first_notice_date` / `last_notice_date` per state: how far back each state reaches. |
| Shared filters | `warn_v2/api/filters.py` `apply_notice_filters` | Includes the `bbox` added in #373. Use it in any new endpoint. |
| State choropleth | `frontend/src/components/UsChoroplethMap.tsx`, `UsMap.tsx` | SVG, no MapLibre needed. A state-level time-lapse could build on it. |
| Colors | `frontend/src/lib/themeColors.ts` | Every JS-drawn color comes from here, keyed by theme. The `dataviz` skill and its Python validator (`validate_palette.py`, set `PYTHONIOENCODING=utf-8`) check new palettes. |

## Data facts that shape the design (measured 2026-10-16 on prod)

- **86,560 notices** in all; 79,044 are geocoded, at ~12.6k distinct places.
- **Volume by year** is fairly steady at 2–3k notices/year from 2001 to 2019. **2020 has 16,437** (COVID). 2023–2025 run at 3.8–4.8k. 1989–1995 hold a handful of stray rows. 2026 is partial.
- **Coverage grows over time. This is the biggest trap.** States with any notices: **16** in 2000, **24** in 2005, **32** in 2010, **41** in 2015, **47** from 2020 on.
  - A naive time-lapse shows layoffs "spreading across the country", when it's really scrapers' archives starting.
  - The graphic must tell "no data yet" apart from "no layoffs", using `first_notice_date` from `/api/scraper-runs/status`. Grey out or hatch states that aren't covered yet, and/or show a "N states reporting" counter.
  - Consider defaulting the window to 2010 or 2015 onward, with full history one click away.
- **Industry is known for only ~61% of notices** (52,569 of 86,560 carry a NAICS sector through their linked `Company`). Enrichment coverage also varies by year and state.
  - The industry graphic must say "of notices with a known industry", or show an "Unclassified" band, never imply full coverage.
  - The industry filter inner-joins `Company`, so untagged notices drop out silently.
- **Sparse cell counts**, measured on a local copy of the geocoded set: one row per (place, period) with at least one notice gives:

  | bucket | periods | non-empty cells |
  |---|---|---|
  | year | 37 | 38.8k |
  | quarter | 133 | 51.8k |
  | month | 381 | 60.3k |

  State × month is only 7.8k cells. Even monthly place data fits in one payload of roughly 150–250 KB gzip as columnar ints, so the client can scrub frames with **no request per frame**.
- **The time axis is `notice_date`** (the filing date), as on every other chart. `effective_date` (when the layoff takes effect) is a different story; don't mix them.
- **`Non-WARN` rows** (state rapid-response events) are excluded from stats by default (`closure_category` default). Keep that consistent.

## Recommended build

These are recommendations, not settled decisions. Raphael has seen none of these specifics yet, so confirm the open questions at the end before building.

### 1. Geographic time-lapse: a heatmap that plays

Build on `PlacesMap`'s heatmap, since that is what landed.

**Endpoint:** `GET /api/map-places/timeline?bucket=year|quarter|month&<standard filters>`. It returns one columnar payload:
- `places`: `lat`, `lon`, `label` (index-aligned, as in map-places);
- `periods`: sorted period keys;
- sparse triples `place_i`, `period_i`, `notices`, `workers` as parallel int arrays.

Implementation notes:
- Group by `round(lat,4), round(lon,4)` plus the period prefix of `notice_date`. Reuse `apply_notice_filters`.
- Set `Cache-Control: public, max-age=300` like its siblings.
- Write tests in `tests/test_api.py` next to the map-places tests (the `_geocoded_notice` helper).
- If quarter or month payloads get big, gzip already applies (middleware level 6). Measure before optimizing.

**Client:**
- Load the payload once. Build one GeoJSON source where each feature carries its period index; drive frames with `map.setFilter("heat", ["==", ["get", "p"], frame])`, or a window such as the trailing 12 months. Benchmark that against `setData` per frame on a throttled mobile profile.
- A scrubber (range input) plus a play/pause button, with speed control and a period label overlaid on the map.
- Keep `frame` and `bucket` in the URL, as `/map` keeps `lat/lon/zoom`.
- **Color scale:** a fixed scale across frames shows magnitude (2020 will glow), while a per-frame scale shows distribution. Recommend a fixed scale clamped at about the 95th percentile so 2020 saturates without washing out other years, plus a small legend. Decide with Raphael.
- **Coverage:** an overlay or counter from `first_notice_date`. The cheapest honest version is a "N of 48 states reporting" badge plus a muted state outline for uncovered states.
- A synced **national sparkline** under the map (from `/api/stats/over-time`) with a playhead, so the viewer sees where the frame sits in the overall curve.

### 2. Industry time-lapse

**Endpoint:** `GET /api/stats/industries/timeline?bucket=year|quarter|month&<filters>` returns sector × period `{notice_count, layoff_total}`. It's small (20 sectors × periods).
- Include an **Unclassified** row: notices with no linked company NAICS. That makes the coverage visible.
- Put it in `stats.py` next to `industries()`, with the same NAICS helpers (`warn_v2/companies/naics.py`).

**Client:** a ranked bar time-lapse ("bar chart race"): sectors sorted by workers in the current period, animated between frames.
- It shares the timeline scrubber and playhead with the map, so both graphics advance together.
- Recharts is already in the bundle, but its animations fight frame-by-frame updates. Plain SVG or CSS-transform bars keyed by sector may be simpler and smoother; decide after a quick spike.
- Use categorical sector colors from a palette validated with the dataviz skill. The `layoffs` red is reserved for WARN counts.
- Tapping a sector filters the map to that industry, which ties "where" and "which industry" together.

### Placement

Pick one with Raphael:
- **A new `/timelapse` page** holding both graphics on one shared timeline. This is the recommendation: it's the clearest story and keeps `/map` focused.
- **A "Play" mode on `/map`** for the geographic graphic, plus the industry race on `/stats` or the dashboard.

Either way, code-split it (MapLibre via `lazyRouteComponent` or the `NoticeMap` lazy pattern), and link it from the nav or the dashboard.

## Non-negotiables

- **Mobile first.** The old map's failure on phones is why #373 exists. Check frame rate on a throttled mobile profile. `PlacesMap` loads ~12.6k features fine on mobile; frames should change filters, not re-upload data.
- **`prefers-reduced-motion`:** no autoplay; the scrubber still works.
- **Accessibility:** the scrubber is a labelled `input[type=range]` with `aria-valuetext` (period + counts). Provide a table or text equivalent for the current frame; the industry bars can double as one.
- **Honesty:** coverage caveats (states, industry) are visible on the graphic itself, not only in a footnote. Narrative copy frames rises as job losses, never "growth" (the README's "Layoffs are job losses" rule).
- Partial current period: show its `projected_*` value as projected or mark it partial, as the existing charts do.

## How to verify locally (prod data, no prod DB access)

#373 used this recipe. The scripts lived in a session scratchpad; recreate them.
1. Page `https://warnindex.com/api/notices?geocoded_only=true&limit=500&offset=N` at 1 req/s into JSONL (about 3 minutes; anonymous limit 120/min). Dedupe by `notice_id`, because offset paging over a live list repeats rows.
2. Build a scratch SQLite DB with `Base.metadata.create_all`, inserting `Location`, `Company` (`id`, `name`, `naics_code`, `website`) and `Notice` from the JSON. Run it with the venv's python **from the worktree as cwd** (`python -c`), so `warn_v2` resolves to the worktree (see `CLAUDE.md`).
3. Run `uvicorn warn_v2.api:app` with `DATABASE_URL=sqlite:///…` and `RATE_ANON_PER_MIN=100000`. Then start vite with `API_PROXY_TARGET=http://localhost:8000`.
4. Check with Playwright: the double-p venv `C:\Users\rapha\workspace\warn_scrapper_v2\.venv` has it. Use a 390×844 mobile context, CDP `Emulation.setCPUThrottlingRate` 4, and a `PerformanceObserver('longtask')` plus a rAF frame-time recorder. Headless WebGL runs on SwiftShader, so the numbers are pessimistic.

Gotchas:
- SQLite stores coordinates as floats, so a few 4-dp roundings differ from Postgres `numeric`. That's a test-env artifact.
- After a merge that renames files, restart vite, kill the port owner and clear `node_modules/.vite`. Otherwise the dev server serves a stale module graph.
- Company logos 404 locally; that's expected.

## Open questions for Raphael (ask before building)

1. **Placement:** a new `/timelapse` page (recommended), or a Play mode on `/map` plus the industry race elsewhere?
2. **Default window and bucket:** for example 2015 → now by quarter, with full history and monthly one click away?
3. **Color scale:** fixed across frames (shows the 2020 spike) or per-frame (shows the distribution)?
4. **Industry form:** a ranked-bar race (recommended), a streamgraph, or small multiples?
5. Should the sector bars drive the map's industry filter (linked views)?

## Related follow-ups noticed but not done

- Old Leaflet-era `/map?zoom=N` share links open about one level closer on MapLibre (512 px tiles).
- `/api/map-pins` has no UI consumer since #373. It stays as public API; decide whether to document or deprecate it.
