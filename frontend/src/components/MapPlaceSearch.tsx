import { useId, useMemo, useState } from "react";

import type { MapPlaces } from "../api/client";
import { fmtNum, STATE_NAMES } from "../lib/format";

export type PlacePick =
  | { kind: "state"; code: string }
  | { kind: "place"; index: number };

const MAX_RESULTS = 8;

/* Jump-to search over the states and the places already on the map — no
   geocoder: every searchable place is one the map has notices for, so the
   list is short, instant, and never offers an empty spot. */
export function MapPlaceSearch({
  places,
  onPick,
}: {
  places: MapPlaces | undefined;
  onPick: (p: PlacePick) => void;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();

  const lowerLabels = useMemo(() => places?.label.map((l) => l.toLowerCase()) ?? [], [places]);

  const results = useMemo(() => {
    const q = text.trim().toLowerCase();
    if (q.length < 2) return [];
    const out: { pick: PlacePick; title: string; detail: string }[] = [];
    for (const [code, name] of Object.entries(STATE_NAMES)) {
      if (name.toLowerCase().startsWith(q) || code.toLowerCase() === q) {
        out.push({ pick: { kind: "state", code }, title: name, detail: "State" });
      }
    }
    // Places arrive busiest-first, so the first matches are the likeliest —
    // and the first of several points sharing a city name (separate geocodes
    // of one city) is the one to offer. Label-less points ("ST") are covered
    // by the state rows above.
    const seen = new Set<string>();
    for (let i = 0; i < lowerLabels.length && out.length < MAX_RESULTS; i++) {
      if (lowerLabels[i].length > 2 && lowerLabels[i].includes(q) && !seen.has(lowerLabels[i])) {
        seen.add(lowerLabels[i]);
        out.push({
          pick: { kind: "place", index: i },
          title: places!.label[i],
          detail: `${fmtNum(places!.notices[i])} notices`,
        });
      }
    }
    return out.slice(0, MAX_RESULTS);
  }, [text, lowerLabels, places]);

  const choose = (i: number) => {
    const r = results[i];
    if (!r) return;
    onPick(r.pick);
    setText(r.title);
    setOpen(false);
  };

  return (
    <div className="relative w-full sm:w-72">
      <input
        type="search"
        role="combobox"
        aria-label="Find a city or state on the map"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        aria-activedescendant={open && results[active] ? `${listId}-${active}` : undefined}
        aria-autocomplete="list"
        placeholder="Find a city or state…"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, results.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            choose(active);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
      />
      {open && results.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          {results.map((r, i) => (
            <li
              key={r.pick.kind === "state" ? r.pick.code : r.pick.index}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              // mousedown, not click: it lands before the input's blur closes the list.
              onMouseDown={(e) => {
                e.preventDefault();
                choose(i);
              }}
              onMouseEnter={() => setActive(i)}
              className={`flex cursor-pointer items-baseline justify-between gap-2 px-3 py-2 text-sm ${
                i === active ? "bg-slate-100 dark:bg-slate-800" : ""
              }`}
            >
              <span className="truncate">{r.title}</span>
              <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">{r.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
