import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";

import { api } from "../api/client";
import { FilterBar, type FilterValues } from "../components/FilterBar";
import { fmtNum } from "../lib/format";

export function FamiliesPage() {
  const navigate = useNavigate({ from: "/families" });
  const search = useSearch({ from: "/families" });

  const query = useQuery({
    queryKey: ["stats", "by-parent-group", search],
    queryFn: () => api.statsByParentGroup({ ...search, limit: 50 }),
  });

  const handleFilterChange = (next: FilterValues) => {
    navigate({ search: () => ({ ...next, employer: undefined, closure_category: undefined }) });
  };

  return (
    <div>
      <div className="mb-3">
        <h1 className="text-2xl font-semibold">Corporate families</h1>
        <p className="mt-1 text-sm text-slate-500">
          Companies grouped into corporate families, ranked by total layoffs across
          all their subsidiaries. Each family is labeled by its largest member.
        </p>
      </div>

      <FilterBar
        values={search}
        onChange={handleFilterChange}
        showEmployer={false}
      />

      {query.isLoading && <div className="card text-sm text-slate-500">Loading…</div>}
      {query.data && query.data.length === 0 && (
        <div className="card text-sm text-slate-500">
          No corporate families found for these filters.
        </div>
      )}
      {query.data && query.data.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2 font-medium">#</th>
                <th className="px-4 py-2 font-medium">Family (largest member)</th>
                <th className="px-4 py-2 text-right font-medium">Members</th>
                <th className="px-4 py-2 text-right font-medium">Notices</th>
                <th className="px-4 py-2 text-right font-medium">Workers affected</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {query.data.map((f, i) => (
                <tr key={f.representative_company_id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 text-slate-400">{i + 1}</td>
                  <td className="px-4 py-2">
                    <Link
                      to="/companies/$companyId"
                      params={{ companyId: String(f.representative_company_id) }}
                      className="font-medium text-sky-700 hover:underline"
                    >
                      {f.representative_company_name}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {fmtNum(f.member_count)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {fmtNum(f.notice_count)}
                  </td>
                  <td className="px-4 py-2 text-right font-medium tabular-nums">
                    {fmtNum(f.layoff_total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
