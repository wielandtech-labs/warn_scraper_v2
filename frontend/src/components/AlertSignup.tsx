import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import { stateName } from "../lib/format";

/**
 * Email-alert signup. Posts to /api/subscriptions (double opt-in — the user
 * gets a confirmation email). Pass `state` to scope alerts to one state.
 */
export function AlertSignup({ state }: { state?: string }) {
  const [email, setEmail] = useState("");
  const scope = state ? stateName(state) : "US";

  const mutation = useMutation({
    mutationFn: () => api.createSubscription({ email: email.trim(), state }),
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
      ? "Please enter a valid email address."
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
      {errorMessage && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errorMessage}</p>
      )}
      <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
        Double opt-in · unsubscribe anytime · we only use your email for these alerts.
      </p>
    </div>
  );
}
