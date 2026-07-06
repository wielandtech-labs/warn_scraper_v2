import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState, type ReactNode } from "react";

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  emptyMessage?: string;
  /** Optional recovery action rendered under the empty message (e.g. clear filters). */
  emptyAction?: ReactNode;
  /** Server-side sort control. When provided, client-side getSortedRowModel is disabled. */
  sortBy?: string;
  sortDir?: "asc" | "desc";
  onSortChange?: (colId: string, dir: "asc" | "desc") => void;
}

export function DataTable<T>({
  data,
  columns,
  emptyMessage = "No results.",
  emptyAction,
  sortBy,
  sortDir,
  onSortChange,
}: DataTableProps<T>) {
  const isServer = Boolean(onSortChange);

  // Client-side sort state — only used when onSortChange is not provided.
  const [localSorting, setLocalSorting] = useState<SortingState>([]);

  const sorting: SortingState = isServer
    ? sortBy
      ? [{ id: sortBy, desc: sortDir === "desc" }]
      : []
    : localSorting;

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: isServer ? undefined : setLocalSorting,
    getCoreRowModel: getCoreRowModel(),
    ...(isServer ? { manualSorting: true } : { getSortedRowModel: getSortedRowModel() }),
  });

  if (data.length === 0) {
    return (
      <div className="card text-center text-sm text-slate-500 dark:text-slate-400">
        <p>{emptyMessage}</p>
        {emptyAction && <div className="mt-3">{emptyAction}</div>}
      </div>
    );
  }

  // Apply a sort regardless of mode — used by the mobile control, which has no
  // column headers to click.
  const applySort = (id: string, dir: "asc" | "desc") => {
    if (isServer) onSortChange!(id, dir);
    else setLocalSorting([{ id, desc: dir === "desc" }]);
  };

  // Columns offered in the mobile sort control: those with a plain-string header
  // (used as the option label) that the active mode allows sorting on.
  const sortableCols = table.getAllLeafColumns().filter((col) => {
    if (typeof col.columnDef.header !== "string") return false;
    return isServer ? col.columnDef.enableSorting !== false : col.getCanSort();
  });
  const activeId = isServer ? sortBy ?? "" : sorting[0]?.id ?? "";
  const activeDir: "asc" | "desc" = isServer
    ? sortDir ?? "desc"
    : sorting[0]?.desc
      ? "desc"
      : "asc";

  return (
    <>
      {sortableCols.length > 0 && (
        <div className="mb-2 flex items-center gap-2 sm:hidden">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Sort
          </span>
          <select
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
            value={activeId || sortableCols[0]?.id || ""}
            onChange={(e) => applySort(e.target.value, activeDir)}
          >
            {sortableCols.map((col) => (
              <option key={col.id} value={col.id}>
                {col.columnDef.header as string}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-secondary"
            aria-label={activeDir === "desc" ? "Sort descending" : "Sort ascending"}
            onClick={() =>
              applySort(
                activeId || sortableCols[0]!.id,
                activeDir === "desc" ? "asc" : "desc",
              )
            }
          >
            {activeDir === "desc" ? "▼" : "▲"}
          </button>
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="data-table w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-950 dark:text-slate-400">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                // getCanSort() requires an accessor, which display columns
                // (id + cell only, e.g. the companies Status column) lack —
                // in server mode the server decides what's sortable, so only
                // an explicit enableSorting: false opts a column out.
                const canSort = isServer
                  ? h.column.columnDef.enableSorting !== false
                  : h.column.getCanSort();
                const sorted: false | "asc" | "desc" = isServer
                  ? sortBy === h.column.id && sortDir
                    ? sortDir
                    : false
                  : h.column.getIsSorted();
                const sortLabel = flexRender(h.column.columnDef.header, h.getContext());
                return (
                  <th
                    key={h.id}
                    aria-sort={
                      sorted === "asc"
                        ? "ascending"
                        : sorted === "desc"
                          ? "descending"
                          : undefined
                    }
                    className={`font-medium ${canSort ? "" : "px-3 py-2"}`}
                  >
                    {canSort ? (
                      // A real <button> so keyboard users can reach and toggle the sort.
                      <button
                        type="button"
                        className="w-full select-none px-3 py-2 text-left font-medium uppercase tracking-wide hover:bg-slate-100 dark:hover:bg-slate-800"
                        onClick={
                          isServer
                            ? () => {
                                const id = h.column.id;
                                onSortChange!(
                                  id,
                                  sortBy === id && sortDir === "desc" ? "asc" : "desc",
                                );
                              }
                            : h.column.getToggleSortingHandler()
                        }
                      >
                        {sortLabel}
                        {sorted === "asc" && " ▲"}
                        {sorted === "desc" && " ▼"}
                      </button>
                    ) : (
                      sortLabel
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  className="px-3 py-2 align-top"
                  data-label={
                    typeof cell.column.columnDef.header === "string"
                      ? cell.column.columnDef.header
                      : ""
                  }
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        </table>
      </div>
    </>
  );
}
