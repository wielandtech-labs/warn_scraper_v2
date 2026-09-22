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

  const [draft, setDraft] = useState(name ?? "");
  const [sources, setSources] = useState<Set<number>>(new Set());
  const [target, setTarget] = useState<number | null>(null);
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
      setSources(new Set());
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
  const selectable = items.filter((c) => c.id !== target);
  const selected = [...sources].filter((id) => id !== target);
  const targetRow = items.find((c) => c.id === target);
  const allChecked = selectable.length > 0 && selectable.every((c) => sources.has(c.id));

  const toggle = (id: number) =>
    setSources((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = () => {
    if (target == null || selected.length === 0) return;
    const label = targetRow?.name ?? `#${target}`;
    if (!window.confirm(`Merge ${selected.length} companies into "${label}"?`)) return;
    merge.mutate({ target_id: target, source_ids: selected, note: note || undefined });
  };

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <h1 className="text-2xl font-semibold">Merge companies</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Search, tick the rows that are the same company, pick the row whose name should
          label the group, then merge. Undo from the company page (“Merged records”).
        </p>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setSources(new Set());
            setTarget(null);
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
                      setSources(allChecked ? new Set() : new Set(selectable.map((c) => c.id)))
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
                <tr key={c.id} className={c.id === target ? "bg-sky-50 dark:bg-sky-950" : ""}>
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Merge ${c.name}`}
                      disabled={c.id === target}
                      checked={sources.has(c.id) && c.id !== target}
                      onChange={() => toggle(c.id)}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="radio"
                      name="target"
                      aria-label={`Use ${c.name} as label`}
                      checked={c.id === target}
                      onChange={() => setTarget(c.id)}
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

      {name && (
        <div className="card flex flex-wrap items-center gap-2">
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
            Merge {selected.length} into {targetRow ? `“${targetRow.name}”` : "…"}
          </button>
        </div>
      )}
    </div>
  );
}
