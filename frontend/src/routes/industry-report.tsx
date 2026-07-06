import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

import { ApiError, api } from "../api/client";
import { QueryError } from "../components/QueryError";
import { ReportMarkdown } from "../components/ReportMarkdown";
import { SkeletonBlock } from "../components/Skeleton";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { GradeBadge } from "./reports";

export function IndustryReportPage() {
  const { sector } = useParams({ from: "/reports/industry/$sector" });

  // Usually already cached from the /reports grid; gives us the display name
  // and grade for the header without parsing the markdown.
  const scorecards = useQuery({
    queryKey: ["reports", "industries"],
    queryFn: api.listIndustryScorecards,
  });
  const card = scorecards.data?.find((c) => c.sector === sector);

  const report = useQuery({
    queryKey: ["report", "industry", sector],
    queryFn: () => api.getIndustryReport(sector),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  });
  const missing =
    report.isError && report.error instanceof ApiError && report.error.status === 404;

  const name = card?.sector_name ?? `NAICS ${sector}`;
  useDocumentTitle(`${name} layoff scorecard — WARN Tracker`);

  if (missing) {
    return (
      <div className="card text-center">
        <p className="text-slate-700">No scorecard for “{sector}”.</p>
        <Link
          to="/reports"
          className="mt-2 inline-block text-sm font-medium text-sky-700 hover:underline"
        >
          ← All industry scorecards
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to="/reports" className="text-sm font-medium text-sky-700 hover:underline">
          ← All industry scorecards
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{name}</h1>
          {card && <GradeBadge grade={card.grade} />}
        </div>
        <p className="mt-1 text-sm text-slate-600">
          NAICS {sector} · weekly national layoff scorecard
        </p>
      </div>

      <div className="card">
        {report.isLoading ? (
          <div className="space-y-2">
            <SkeletonBlock className="h-4 w-1/3" />
            <SkeletonBlock className="h-24 w-full" />
            <SkeletonBlock className="h-4 w-2/3" />
          </div>
        ) : report.isError ? (
          <QueryError
            message="Error loading the scorecard."
            onRetry={() => report.refetch()}
          />
        ) : report.data ? (
          <ReportMarkdown markdown={report.data} skipH1 />
        ) : null}
      </div>

      <p className="text-xs text-slate-500">
        Drill into the underlying notices on the{" "}
        <Link
          to="/notices"
          search={{ industry: sector }}
          className="font-medium text-sky-700 hover:underline"
        >
          notices list
        </Link>{" "}
        filtered to this sector.
      </p>
    </div>
  );
}
