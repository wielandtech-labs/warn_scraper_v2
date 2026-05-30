import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  emptyMessage?: string;
  /** Server-side sort control. When provided, client-side getSortedRowModel is disabled. */
  sortBy?: string;
  sortDir?: "asc" | "desc";
  onSortChange?: (colId: string, dir: "asc" | "desc") => void;
}

export function DataTable<T>({
  data,
  columns,
  emptyMessage = "No results.",
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
      <div className="card text-center text-sm text-slate-500">{emptyMessage}</div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const canSort = h.column.getCanSort();
                return (
                  <th
                    key={h.id}
                    className={`px-3 py-2 font-medium ${canSort ? "cursor-pointer select-none hover:bg-slate-100" : ""}`}
                    onClick={
                      isServer && canSort
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
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {h.column.getIsSorted() === "asc" && " ▲"}
                    {h.column.getIsSorted() === "desc" && " ▼"}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-slate-100">
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="hover:bg-slate-50">
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-3 py-2 align-top">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
