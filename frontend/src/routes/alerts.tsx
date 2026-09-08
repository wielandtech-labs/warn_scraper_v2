import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { AlertFilters, SubscriptionOut } from "../api/types";
import { AlertFilterFields } from "../components/AlertFilterFields";
import { AlertSignup } from "../components/AlertSignup";
import { useAuth } from "../hooks/useAuth";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/** The filter set of an existing alert, in the shape the API expects back. */
function toFilters(sub: SubscriptionOut): AlertFilters {
  return {
    state: sub.state ?? null,
    industry: sub.industry ?? null,
    subsector: sub.subsector ?? null,
    employer_query: sub.employer_query ?? null,
    min_layoffs: sub.min_layoffs ?? null,
    closure_category: sub.closure_category ?? null,
    frequency: sub.frequency,
  };
}

function AlertRow({ sub, token }: { sub: SubscriptionOut; token?: string }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<AlertFilters>(() => toFilters(sub));

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
  const save = useMutation({
    mutationFn: () => api.updateSubscription(sub.id, draft, token),
    onSuccess: () => {
      setEditing(false);
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteSubscription(sub.id, token),
    onSuccess: invalidate,
  });
  const resend = useMutation({
    mutationFn: () => api.resendConfirmation(sub.id, token),
    onSuccess: invalidate,
  });

  return (
    <li className="border-t border-slate-200 py-3 first:border-t-0 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">{sub.scope}</p>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            {sub.frequency === "weekly" ? "Weekly" : "Daily"} ·{" "}
            {sub.confirmed ? "Active" : "Awaiting email confirmation"}
          </p>
        </div>
        <div className="flex gap-2">
          {!sub.confirmed && (
            <button
              type="button"
              className="btn-secondary"
              disabled={resend.isPending}
              onClick={() => resend.mutate()}
            >
              {resend.isSuccess ? "Sent" : "Resend link"}
            </button>
          )}
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setDraft(toFilters(sub));
              setEditing((v) => !v);
            }}
          >
            {editing ? "Cancel" : "Edit"}
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            Remove
          </button>
        </div>
      </div>

      {editing && (
        <div className="mt-3">
          <AlertFilterFields values={draft} onChange={setDraft} />
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={save.isPending}
              onClick={() => save.mutate()}
            >
              {save.isPending ? "Saving…" : "Save changes"}
            </button>
            {save.isError && (
              <span className="text-sm text-red-600 dark:text-red-400">
                Could not save those criteria.
              </span>
            )}
          </div>
        </div>
      )}
      {remove.isError && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">
          Could not remove that alert.
        </p>
      )}
    </li>
  );
}

/** The list itself, once we hold either an emailed token or a verified session. */
function AlertList({ token }: { token?: string }) {
  const subs = useQuery({
    queryKey: ["subscriptions", token ?? "session"],
    queryFn: () => api.listSubscriptions(token),
    retry: false,
  });

  if (subs.isLoading) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>;
  }
  if (subs.error instanceof ApiError && subs.error.status === 404) {
    return (
      <>
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-300">
          That management link is no longer valid — it points at an alert that
          has been removed.
        </p>
        <RequestLinkCard />
      </>
    );
  }
  if (subs.error instanceof ApiError && subs.error.status === 401) {
    // Signed in, but the account's email isn't verified — that proves nothing
    // about owning the address, so fall back to the emailed link.
    return (
      <>
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-300">
          Verify your account email to see your alerts here, or use a link
          emailed to the address you subscribed with.
        </p>
        <RequestLinkCard />
      </>
    );
  }
  if (subs.isError) {
    return (
      <p className="text-sm text-red-600 dark:text-red-400">
        Could not load your alerts. Please try again later.
      </p>
    );
  }

  const rows = subs.data ?? [];
  return (
    <>
      <div className="card">
        <h2 className="text-lg font-semibold">Your alerts</h2>
        {rows.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            No alerts yet. Create one below.
          </p>
        ) : (
          <ul className="mt-2">
            {rows.map((sub) => (
              <AlertRow key={sub.id} sub={sub} token={token} />
            ))}
          </ul>
        )}
      </div>
      <div className="mt-4">
        {/* Signing up again from here goes through the same double opt-in, so a
            new alert still needs a click in the confirmation email. */}
        <AlertSignup defaultOpen />
      </div>
    </>
  );
}

/** Anonymous entry point: ask for the emailed link. */
function RequestLinkCard() {
  const [email, setEmail] = useState("");
  const request = useMutation({ mutationFn: () => api.requestManageLink(email.trim()) });

  return (
    <div className="card">
      <h2 className="text-lg font-semibold">Manage your alerts</h2>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
        Enter the address you subscribed with and we&apos;ll email you a link to
        view, change or remove your alerts.
      </p>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (email.trim()) request.mutate();
        }}
      >
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
        />
        <button type="submit" disabled={request.isPending} className="btn-primary shrink-0">
          {request.isPending ? "Sending…" : "Email me a link"}
        </button>
      </form>
      {request.isSuccess && (
        // Deliberately non-committal: the API answers the same for an address
        // with no alerts, so the page must not imply one exists.
        <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">
          If that address has alerts, a management link is on its way.
        </p>
      )}
      {request.isError && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">
          {request.error instanceof ApiError && request.error.status === 422
            ? "Please enter a valid email address."
            : "Something went wrong. Please try again later."}
        </p>
      )}
      <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
        Every alert email also carries this link.{" "}
        <Link to="/login" className="underline">
          Signed in
        </Link>{" "}
        with a verified account? Your alerts appear here automatically.
      </p>
    </div>
  );
}

export function AlertsPage() {
  useDocumentTitle("Your alerts — WARN Tracker");
  const { token } = useSearch({ from: "/alerts" });
  const auth = useAuth();
  // A session lists the same alerts without a token — the API accepts it only
  // when the account's email is verified, and AlertList handles the 401 if not.
  const sessionCanList = !!auth.data;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-xl font-semibold">Email alerts</h1>
      <p className="mt-1 mb-4 text-sm text-slate-500 dark:text-slate-400">
        Each alert is one saved search. We email you when new WARN notices match
        it.
      </p>
      {token || sessionCanList ? <AlertList token={token} /> : <RequestLinkCard />}
    </div>
  );
}
