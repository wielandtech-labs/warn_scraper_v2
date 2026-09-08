import { useMutation } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { AlertFilters } from "../api/types";
import { stateName } from "../lib/format";
import { AlertFilterFields } from "./AlertFilterFields";

/**
 * Email-alert signup. Posts to /api/subscriptions (double opt-in — the user
 * gets a confirmation email). Pass `state` to scope alerts to one state, or
 * `initialFilters` to seed the criteria from what the page is already showing
 * (the notices list does this so a filtered search becomes an alert in one
 * step). The extra criteria live behind a disclosure so the common case stays
 * a single email field.
 */
export function AlertSignup({
  state,
  initialFilters,
  defaultOpen = false,
}: {
  state?: string;
  initialFilters?: AlertFilters;
  defaultOpen?: boolean;
}) {
  const [email, setEmail] = useState("");
  const [filters, setFilters] = useState<AlertFilters>({
    frequency: "daily",
    ...initialFilters,
    ...(state ? { state } : {}),
  });
  const [showFilters, setShowFilters] = useState(defaultOpen);
  const scope = state ? stateName(state) : "US";

  const mutation = useMutation({
    mutationFn: () => api.createSubscription({ ...filters, email: email.trim() }),
  });

  if (mutation.isSuccess) {
    return (
      <div className="card bg-sky-50 dark:bg-sky-950">
        <p className="text-sm text-slate-700 dark:text-slate-300">
          Almost there — check <strong>{email}</strong> for a confirmation link to
          start receiving alerts.
        </p>
      </div>
    );
  }

  const errorMessage =
    mutation.error instanceof ApiError && mutation.error.status === 422
      ? "Please check the email address and the alert criteria."
      : mutation.error instanceof ApiError && mutation.error.status === 400
        ? "This address already has the maximum number of alerts; remove one first."
        : mutation.isError
          ? "Something went wrong. Please try again later."
          : null;

  return (
    <div className="card">
      <h2 className="text-lg font-semibold">Get {scope} layoff alerts</h2>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
        Email me when new WARN notices{state ? ` in ${scope}` : ""} are filed.
      </p>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (email.trim()) mutation.mutate();
        }}
      >
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-400 dark:border-slate-700 dark:bg-slate-900 dark:focus:border-sky-500 dark:focus:ring-sky-500"
        />
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-60"
        >
          {mutation.isPending ? "Subscribing…" : "Subscribe"}
        </button>
      </form>

      <button
        type="button"
        className="mt-2 text-sm text-sky-700 underline dark:text-sky-400"
        onClick={() => setShowFilters((v) => !v)}
      >
        {showFilters ? "Hide options" : "Narrow by industry, size or employer"}
      </button>
      {showFilters && (
        <div className="mt-3">
          <AlertFilterFields
            values={filters}
            onChange={setFilters}
            showState={!state}
          />
        </div>
      )}

      {errorMessage && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errorMessage}</p>
      )}
      <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
        Double opt-in · unsubscribe anytime · we only use your email for these
        alerts.{" "}
        <Link to="/alerts" className="underline">
          Manage your alerts
        </Link>
      </p>
    </div>
  );
}
