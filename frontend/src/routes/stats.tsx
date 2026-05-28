import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import { FilterBar, type FilterValues } from "../components/FilterBar";
import { fmtMonth, fmtNum } from "../lib/format";

export function StatsPage() {
  const navigate = useNavigate({ from: "/stats" });
  const search = useSearch({ from: "/stats" });

  const byMonth = useQuery({
    queryKey: ["stats", "by-month", search],
    queryFn: () => api.statsByMonth(search),
  });

  const byState = useQuery({
    queryKey: ["stats", "by-state", search],
    queryFn: () =>
      api.statsByState({ after: search.after, before: search.before }),
  });

  const top = useQuery({
    queryKey: ["stats", "top-employers", search, 20],
    queryFn: () => api.statsTopEmployers({ ...search, limit: 20 }),
  });

  const handleFilterChange = (next: FilterValues) => {
    navigate({ search: () => ({ ...next, employer: undefined }) });
  };

  const monthData = (byMonth.data ?? []).map((r) => ({
    ...r,
    monthLabel: fmtMonth(r.month),
  }));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Statistics</h1>
      <FilterBar values={search} onChange={handleFilterChange} showEmployer={false} />

      <ChartCard title="Notices and layoffs by month">
        {byMonth.isLoading ? (
          <Placeholder />
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={monthData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="monthLabel" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v: number) => fmtNum(v)} />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="notice_count"
                name="Notices"
                stroke="#0369a1"
                strokeWidth={2}
                dot={false}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="layoff_total"
                name="Workers affected"
                stroke="#dc2626"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="By state">
        {byState.isLoading ? (
          <Placeholder />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(300, (byState.data?.length ?? 0) * 18)}>
            <BarChart
              layout="vertical"
              data={(byState.data ?? []).slice().sort((a, b) => b.layoff_total - a.layoff_total)}
              margin={{ left: 10 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis type="number" tick={{ fontSize: 12 }} />
              <YAxis dataKey="state" type="category" tick={{ fontSize: 12 }} width={40} />
              <Tooltip formatter={(v: number) => fmtNum(v)} />
              <Bar dataKey="layoff_total" name="Workers affected" fill="#0369a1" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="Top 20 employers">
        {top.isLoading ? (
          <Placeholder />
        ) : (
          <ResponsiveContainer width="100%" height={500}>
            <BarChart
              layout="vertical"
              data={top.data ?? []}
              margin={{ left: 20 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis type="number" tick={{ fontSize: 12 }} />
              <YAxis
                dataKey="employer"
                type="category"
                tick={{ fontSize: 11 }}
                width={200}
              />
              <Tooltip formatter={(v: number) => fmtNum(v)} />
              <Bar dataKey="layoff_total" name="Workers affected" fill="#dc2626" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="card">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {children}
    </div>
  );
}

function Placeholder() {
  return <div className="flex h-72 items-center justify-center text-slate-500">Loading…</div>;
}
