import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api, ApiError } from "../api/client";
import type { ApiKeyCreatedOut } from "../api/types";
import { useAuth } from "../hooks/useAuth";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString();
}

/** The raw key, shown exactly once after creation. */
function NewKeyBanner({ created }: { created: ApiKeyCreatedOut }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950">
      <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
        Copy your new key now — it won't be shown again.
      </p>
      <div className="mt-2 flex items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded bg-white px-2 py-1 text-xs dark:bg-slate-900">
          {created.key}
        </code>
        <button
          type="button"
          className="btn-secondary shrink-0"
          onClick={() => {
            navigator.clipboard.writeText(created.key).then(() => setCopied(true));
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

function KeysCard() {
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: ["keys"], queryFn: api.listKeys });
  const [name, setName] = useState("");
  const [lastCreated, setLastCreated] = useState<ApiKeyCreatedOut | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["keys"] });
    queryClient.invalidateQueries({ queryKey: ["usage"] });
  };
  const create = useMutation({
    mutationFn: () => api.createKey(name.trim() || undefined),
    onSuccess: (created) => {
      setLastCreated(created);
      setName("");
      invalidate();
    },
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api.revokeKey(id),
    onSuccess: invalidate,
  });

  const createError =
    create.error instanceof ApiError && create.error.status === 403
      ? "Verify your email first — check your inbox for the verification link."
      : create.error instanceof ApiError && create.error.status === 400
        ? "Active key limit reached; revoke one first."
        : create.isError
          ? "Could not create the key. Please try again."
          : null;

  const active = (keys.data ?? []).filter((k) => !k.revoked_at);
  const revoked = (keys.data ?? []).filter((k) => k.revoked_at);

  return (
    <div className="card">
      <h2 className="text-lg font-semibold">API keys</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Send as <code>X-API-Key</code> or <code>Authorization: Bearer</code>. See{" "}
        <Link to="/api-docs" className="text-sky-700 underline dark:text-sky-400">
          Data &amp; API
        </Link>{" "}
        for limits per tier.
      </p>

      {lastCreated && <NewKeyBanner created={lastCreated} />}

      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <input
          type="text"
          maxLength={64}
          placeholder="Key name (optional, e.g. “ingest job”)"
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" disabled={create.isPending} className="btn-primary shrink-0">
          {create.isPending ? "Creating…" : "Create key"}
        </button>
      </form>
      {createError && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">{createError}</p>
      )}

      {keys.isLoading ? (
        <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">Loading…</p>
      ) : active.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">No active keys yet.</p>
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <th className="py-1 pr-2">Key</th>
              <th className="py-1 pr-2">Name</th>
              <th className="py-1 pr-2">Created</th>
              <th className="py-1 pr-2">Last used</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {active.map((k) => (
              <tr key={k.id} className="border-t border-slate-200 dark:border-slate-800">
                <td className="py-2 pr-2">
                  <code>{k.prefix}…</code>
                </td>
                <td className="py-2 pr-2">{k.name || "—"}</td>
                <td className="py-2 pr-2">{fmtDate(k.created_at)}</td>
                <td className="py-2 pr-2">{fmtDate(k.last_used_at)}</td>
                <td className="py-2 text-right">
                  <button
                    type="button"
                    className="text-sm font-medium text-red-600 hover:underline dark:text-red-400"
                    disabled={revoke.isPending}
                    onClick={() => {
                      if (window.confirm(`Revoke key ${k.prefix}…? This cannot be undone.`)) {
                        revoke.mutate(k.id);
                      }
                    }}
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {revoked.length > 0 && (
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          {revoked.length} revoked key{revoked.length > 1 ? "s" : ""} hidden.
        </p>
      )}
    </div>
  );
}

function UsageCard() {
  const usage = useQuery({ queryKey: ["usage"], queryFn: api.usage });
  if (usage.isLoading || !usage.data) return null;
  const u = usage.data;
  const pct =
    u.daily_limit && u.daily_limit > 0
      ? Math.min(100, Math.round((u.today / u.daily_limit) * 100))
      : 0;
  return (
    <div className="card">
      <h2 className="text-lg font-semibold">Usage today</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        {u.today.toLocaleString()} requests
        {u.daily_limit ? ` of ${u.daily_limit.toLocaleString()} daily` : ""}
        {u.per_minute_limit ? ` · ${u.per_minute_limit}/min burst` : ""}
      </p>
      {u.daily_limit ? (
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
          <div
            className={`h-full ${pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-amber-500" : "bg-sky-600"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      ) : null}
      {u.keys.length > 1 && (
        <ul className="mt-3 space-y-1 text-sm text-slate-600 dark:text-slate-400">
          {u.keys.map((k) => (
            <li key={k.prefix}>
              <code>{k.prefix}…</code> {k.name ? `(${k.name})` : ""} —{" "}
              {k.today.toLocaleString()} today
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PlanCard({ role }: { role: string }) {
  const queryClient = useQueryClient();
  const checkout = useMutation({
    mutationFn: api.billingCheckout,
    onSuccess: ({ url }) => {
      window.location.href = url;
    },
  });
  const portal = useMutation({
    mutationFn: api.billingPortal,
    onSuccess: ({ url }) => {
      window.location.href = url;
    },
  });
  // Returning from Stripe: the webhook may have flipped the role — refetch.
  useEffect(() => {
    if (window.location.search.includes("checkout=")) {
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    }
  }, [queryClient]);

  const billingUnavailable =
    (checkout.error instanceof ApiError && checkout.error.status === 503) ||
    (portal.error instanceof ApiError && portal.error.status === 503);

  return (
    <div className="card">
      <h2 className="text-lg font-semibold">Plan</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Current tier: <span className="font-medium capitalize">{role}</span>
      </p>
      <div className="mt-3 flex gap-2">
        {role === "free" && (
          <button
            type="button"
            className="btn-primary"
            disabled={checkout.isPending}
            onClick={() => checkout.mutate()}
          >
            {checkout.isPending ? "Redirecting…" : "Upgrade to Paid"}
          </button>
        )}
        {role === "paid" && (
          <button
            type="button"
            className="btn-secondary"
            disabled={portal.isPending}
            onClick={() => portal.mutate()}
          >
            {portal.isPending ? "Redirecting…" : "Manage billing"}
          </button>
        )}
        {(role === "enterprise" || role === "admin") && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Your plan is managed directly — contact us for changes.
          </p>
        )}
      </div>
      {billingUnavailable && (
        <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
          Billing isn't open yet — check back soon.
        </p>
      )}
    </div>
  );
}

export function AccountPage() {
  useDocumentTitle("Account — WARN Tracker");
  const auth = useAuth();

  if (auth.isLoading) return null;
  if (!auth.data) {
    return (
      <div className="card mx-auto max-w-md text-center">
        <h1 className="text-xl font-semibold">Account</h1>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          <Link to="/login" className="text-sky-700 underline dark:text-sky-400">
            Sign in
          </Link>{" "}
          or{" "}
          <Link to="/signup" className="text-sky-700 underline dark:text-sky-400">
            create an account
          </Link>{" "}
          to manage API keys.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">Account</h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">{auth.data.email}</p>
      <PlanCard role={auth.data.role} />
      <KeysCard />
      <UsageCard />
    </div>
  );
}
