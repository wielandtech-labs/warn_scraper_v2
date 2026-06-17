import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { fmtDate } from "../lib/format";

/**
 * Global search / autocomplete in the header. Debounced; queries /api/search
 * once the term is ≥2 chars and shows matching companies and notices. Selecting
 * a result navigates to its detail page.
 */
export function SearchBox() {
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value.trim()), 200);
    return () => clearTimeout(t);
  }, [value]);

  const results = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: open && debounced.length >= 2,
  });

  const close = () => {
    setOpen(false);
    setValue("");
  };

  const data = results.data;
  const hasResults = !!data && (data.companies.length > 0 || data.notices.length > 0);
  const showPanel = open && debounced.length >= 2;

  return (
    <div className="relative">
      <input
        type="search"
        value={value}
        placeholder="Search companies or notices…"
        aria-label="Search companies or notices"
        className="w-44 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-400 sm:w-56"
        onChange={(e) => {
          setValue(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") close();
        }}
        onBlur={() => {
          // Delay so an item's onClick fires before the panel unmounts.
          blurTimer.current = setTimeout(() => setOpen(false), 150);
        }}
      />
      {showPanel && (
        <div
          className="absolute right-0 z-20 mt-1 max-h-96 w-80 overflow-auto rounded-md border border-slate-200 bg-white shadow-lg"
          onMouseDown={() => {
            // Keep focus/panel alive through the click on an item.
            if (blurTimer.current) clearTimeout(blurTimer.current);
          }}
        >
          {results.isLoading && (
            <div className="px-3 py-2 text-sm text-slate-500">Searching…</div>
          )}
          {!results.isLoading && !hasResults && (
            <div className="px-3 py-2 text-sm text-slate-500">No matches.</div>
          )}
          {data && data.companies.length > 0 && (
            <div>
              <div className="border-b border-slate-100 bg-slate-50 px-3 py-1 text-xs font-medium uppercase tracking-wide text-slate-400">
                Companies
              </div>
              {data.companies.map((c) => (
                <button
                  key={`c${c.id}`}
                  type="button"
                  className="block w-full truncate px-3 py-2 text-left text-sm hover:bg-sky-50"
                  onClick={() => {
                    close();
                    navigate({
                      to: "/companies/$companyId",
                      params: { companyId: String(c.id) },
                    });
                  }}
                >
                  {c.name}
                </button>
              ))}
            </div>
          )}
          {data && data.notices.length > 0 && (
            <div>
              <div className="border-b border-slate-100 bg-slate-50 px-3 py-1 text-xs font-medium uppercase tracking-wide text-slate-400">
                Notices
              </div>
              {data.notices.map((n) => (
                <button
                  key={`n${n.notice_id}`}
                  type="button"
                  className="block w-full px-3 py-2 text-left text-sm hover:bg-sky-50"
                  onClick={() => {
                    close();
                    navigate({
                      to: "/notices/$noticeId",
                      params: { noticeId: n.notice_id },
                    });
                  }}
                >
                  <span className="truncate font-medium">{n.employer}</span>
                  <span className="ml-2 text-xs text-slate-500">
                    {n.state} · {fmtDate(n.notice_date)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
