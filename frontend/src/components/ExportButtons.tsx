type ExportParam = string | number | boolean | undefined | null;

/**
 * CSV/JSON download links for a list endpoint's export route, carrying the
 * current filters. Plain same-origin <a> downloads — the server sets the
 * Content-Disposition. Anonymous/free downloads are row-capped server-side.
 */
export function ExportButtons({
  basePath,
  params,
}: {
  basePath: string;
  params: Record<string, ExportParam>;
}) {
  const href = (format: "csv" | "json") => {
    const sp = new URLSearchParams({ format });
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
    }
    return `${basePath}?${sp.toString()}`;
  };
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-slate-400">Export</span>
      <a
        className="rounded-md border border-slate-300 px-2 py-1 font-medium text-slate-700 hover:bg-slate-50"
        href={href("csv")}
      >
        CSV
      </a>
      <a
        className="rounded-md border border-slate-300 px-2 py-1 font-medium text-slate-700 hover:bg-slate-50"
        href={href("json")}
      >
        JSON
      </a>
    </div>
  );
}
