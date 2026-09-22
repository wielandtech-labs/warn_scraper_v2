import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";

import { api } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fmtNum } from "../lib/format";

// Admin-only: merge duplicate company rows (e.g. ~100 "Kmart -- Store # …"
// variants) into one company. Decisions are stored as overrides that the
// nightly consolidator re-applies, so they stick.
export function AdminCompaniesPage() {
  useDocumentTitle("Merge companies — WARN Tracker");
  const auth = useAuth();
  const { name } = useSearch({ from: "/admin/companies" });
  const navigate = useNavigate({ from: "/admin/companies" });
  const queryClient = useQueryClient();

  // Selections survive a new search: the rows to merge and the row that labels
  // them often turn up under different search terms ("k-mart" vs "kmart"), so
  // both carry their names with them and are only cleared explicitly.
  const [draft, setDraft] = useState(name ?? "");
  const [sources, setSources] = useState<Map<number, string>>(new Map());
  const [target, setTarget] = useState<{ id: number; name: string } | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const isAdmin = auth.data?.role === "admin";
  const results = useQuery({
    queryKey: ["admin", "companies", name],
    queryFn: () =>
      api.listCompanies({ name, include_merged: true, sort_by: "name", sort_dir: "asc", limit: 500 }),
    enabled: isAdmin && !!name,
  });

  const merge = useMutation({
    mutationFn: api.adminMergeCompanies,
    onSuccess: async (res) => {
      setMessage(`Merged — ${res.updated} rows updated; group label is company #${res.canonical_id}.`);
      setSources(new Map());
      setTarget(null);
      setNote("");
      // Merges change rollups everywhere (top employers, company pages, lists).
      await queryClient.invalidateQueries();
    },
    onError: (e) => setMessage(`Merge failed: ${(e as Error).message}`),
  });

  if (auth.isLoading) return null;
  if (!isAdmin) {
    return <div className="card text-red-600 dark:text-red-400">Admin access required.</div>;
  }

  const items = results.data?.items ?? [];
  const selectable = items.filter((c) => c.id !== target?.id);
  const selected = [...sources.keys()].filter((id) => id !== target?.id);
  const allChecked = selectable.length > 0 && selectable.every((c) => sources.has(c.id));

  const toggle = (id: number, rowName: string) =>
    setSources((prev) => {
      const next = new Map(prev);
      if (next.has(id)) next.delete(id);
      else next.set(id, rowName);
      return next;
    });

  const submit = () => {
    if (target == null || selected.length === 0) return;
    if (!window.confirm(`Merge ${selected.length} companies into "${target.name}"?`)) return;
    merge.mutate({ target_id: target.id, source_ids: selected, note: note || undefined });
  };

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <h1 className="text-2xl font-semibold">Merge companies</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Search, tick the rows that are the same company, pick the row whose name should
          label the group, then merge. Ticks and the label row survive a new search, so
          spelling variants (“kmart”, “k-mart”) can go into one merge. Undo from the
          company page (“Merged records”).
        </p>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setMessage(null);
            navigate({ search: { name: draft.trim() || undefined } });
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Company name contains…"
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
          />
          <button type="submit" className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700">
            Search
          </button>
        </form>
        {message && <div className="text-sm text-slate-700 dark:text-slate-300">{message}</div>}
      </div>

      {name && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={allChecked}
                    onChange={() =>
                      setSources((prev) => {
                        const next = new Map(prev);
                        // Only the rows on screen; ticks from other searches stay.
                        for (const c of selectable) {
                          if (allChecked) next.delete(c.id);
                          else next.set(c.id, c.name);
                        }
                        return next;
                      })
                    }
                  />
                </th>
                <th className="px-3 py-2">Label</th>
                <th className="px-3 py-2">Company</th>
                <th className="px-3 py-2 text-right">Affected</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {results.isLoading && (
                <tr><td colSpan={4} className="px-3 py-3 text-slate-500">Loading…</td></tr>
              )}
              {items.map((c) => (
                <tr key={c.id} className={c.id === target?.id ? "bg-sky-50 dark:bg-sky-950" : ""}>
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Merge ${c.name}`}
                      disabled={c.id === target?.id}
                      checked={sources.has(c.id) && c.id !== target?.id}
                      onChange={() => toggle(c.id, c.name)}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="radio"
                      name="target"
                      aria-label={`Use ${c.name} as label`}
                      checked={c.id === target?.id}
                      onChange={() => setTarget({ id: c.id, name: c.name })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      to="/companies/$companyId"
                      params={{ companyId: String(c.id) }}
                      search={{}}
                      className="text-sky-700 hover:underline dark:text-sky-400"
                    >
                      {c.name}
                    </Link>
                    <span className="ml-2 text-xs text-slate-500">#{c.id}</span>
                    {c.canonical_company_id != null && (
                      <span className="ml-2 text-xs text-slate-500">
                        → merged into #{c.canonical_company_id}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {c.canonical_company_id != null ? "—" : fmtNum(c.layoff_total ?? 0)}
                  </td>
                </tr>
              ))}
              {results.data && items.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-3 text-slate-500">No matches.</td></tr>
              )}
            </tbody>
          </table>
          {results.data && results.data.total > items.length && (
            <div className="px-3 py-2 text-xs text-slate-500">
              Showing {items.length} of {results.data.total} — narrow the search.
            </div>
          )}
        </div>
      )}

      {(selected.length > 0 || target) && (
        <div className="card space-y-3">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
            <span>
              <span className="text-slate-500 dark:text-slate-400">Label: </span>
              {target ? (
                <>
                  {target.name}{" "}
                  <button
                    type="button"
                    onClick={() => setTarget(null)}
                    className="text-xs text-slate-500 hover:underline"
                  >
                    clear
                  </button>
                </>
              ) : (
                <span className="text-amber-700 dark:text-amber-500">
                  none — pick one in the Label column (search for it if it isn’t listed)
                </span>
              )}
            </span>
            <span>
              <span className="text-slate-500 dark:text-slate-400">Ticked: </span>
              {selected.length}{" "}
              {selected.length > 0 && (
                <button
                  type="button"
                  onClick={() => setSources(new Map())}
                  className="text-xs text-slate-500 hover:underline"
                >
                  clear
                </button>
              )}
            </span>
          </div>
          {selected.length > 0 && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {selected.map((id) => sources.get(id)).join(" · ")}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Note (optional)"
              className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
            />
            <button
              type="button"
              onClick={submit}
              disabled={target == null || selected.length === 0 || merge.isPending}
              className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
            >
              Merge {selected.length} into {target ? `“${target.name}”` : "…"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
