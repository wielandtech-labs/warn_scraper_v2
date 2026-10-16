---
name: logo-search
description: Best-effort company logo search for warnindex.com — work the admin logo queue, find a real raster logo for each company with web search, and store it through the validated admin API
argument-hint: "[N]  (companies this run, default 40)"
---

# Find company logos

`/api/logos/{id}` serves an admin-set `companies.logo_url` first, else the
company site's own favicon. Many companies show only a monogram: defunct
brands with no website, sites that block bots or serve SVG-only icons, and
16px favicons that look blurry in a 56px tile. You fill those in, biggest
employers first.

All calls go through the helper next to this file (stdlib only, any Python):

```
python .claude/skills/logo-search/logo_search.py queue 40
python .claude/skills/logo-search/logo_search.py probe ID
python .claude/skills/logo-search/logo_search.py wikifile "File:Some logo.svg"
python .claude/skills/logo-search/logo_search.py set ID URL
python .claude/skills/logo-search/logo_search.py set ID none
```

It reads the admin API key from `WARNINDEX_ADMIN_KEY` or
`~/.warnindex/admin-key`. Never print, echo or cat the key. If the key is
missing, stop and tell the user to mint an admin API key on warnindex.com and
save it to that file.

**Done means:** every company in this run's queue got exactly one `set`
(a URL or `none`), and you printed the summary table below.

## Per company

1. **Probe.** `probe ID`. If `source` is `favicon` and `width >= 64`, the
   current logo is fine: `set ID none` and move on. This stamps it so the queue
   skips it for 90 days.
2. **Identify the company.** Use the queue fields: `name`, `states`,
   `last_notice_year` and `website` (which may be null). WARN employer strings
   are messy. Strip store numbers, "d/b/a" chains and legal suffixes. Resolve to
   the brand a reader would recognise, e.g. "KMART CORPORATION # 7435" → Kmart,
   "Desert Palace Inc. - Caesars LV" → Caesars Palace. A subsidiary with no logo
   of its own may use the parent's (Sky Chefs → LSG Sky Chefs).
   Use the logo **from the notice era** when the brand changed (a 2008 Circuit
   City notice gets Circuit City's logo, not a successor's).
3. **Find a logo**, in this order:
   a. **Wikipedia / Wikimedia Commons.** WebSearch or WebFetch the company's
      Wikipedia article, take the infobox logo's `File:` name, then run
      `wikifile "File:..."`. It returns a PNG thumbnail URL (SVGs are rendered)
      plus the original `width`/`height`. Prefer a square-ish **symbol or icon
      file** (e.g. "Walmart Spark.svg") over a long wordmark: tiles are square
      and `object-contain`, so a 5:1 wordmark becomes an unreadable strip.
      Use a wordmark only when it is the brand's sole logo and the aspect ratio
      is at most about 3:1.
   b. **The official site**, for companies with no Wikipedia logo: an
      `apple-touch-icon` or a large PNG icon declared in the homepage `<head>`,
      or a PNG/JPEG logo on its press or brand page. It must be https, and it
      must be a direct image URL (not an HTML page).
4. **Store it.** `set ID URL`. The server re-fetches the URL under its SSRF
   guard and rejects (422) anything that is not a PNG/ICO/JPEG/WebP of at
   least 64px width and at most 300KB. On a 422, try **one** other candidate,
   then `set ID none`.

**Never guess.** A wrong logo on a layoff notice misattributes the layoff,
which is worse than a monogram. `set ID none` when:
- the name is ambiguous (a common name, with nothing in the state/year to pin
  it down)
- it is a staffing shell, a numbered store, or a multi-entity string
  ("A, B and C LLC") with no clear brand
- it is a person's name, a school district or a government body with no
  official mark you can confirm
- the only candidates are third-party logo aggregator sites, or a photo
  rather than a logo

## Budget

The run uses the user's subscription, not the API, so keep it light. Handle at
most N companies (the argument, default 40), with at most about 3 searches or
fetches per company. Stop early if the queue is empty.

## Summary

End with a table, one row per company: id, name, outcome
(`set` / `favicon-ok` / `miss` / `ambiguous` / `rejected`), and the URL source
(wikipedia / official site). Then give counts per outcome.
