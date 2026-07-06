import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";

import { api, ApiError } from "../api/client";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export function LoginPage() {
  useDocumentTitle("Sign in — WARN Tracker");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const login = useMutation({
    mutationFn: () => api.login(email, password),
    onSuccess: async () => {
      // Cached payloads are role-shaped (paid sessions get extra company
      // fields), so drop everything — not just ["auth", "me"].
      await queryClient.invalidateQueries();
      navigate({ to: "/" });
    },
  });

  const forgot = useMutation({
    mutationFn: () => api.forgotPassword(email),
  });

  const errorMsg =
    login.error instanceof ApiError && login.error.status === 401
      ? "Invalid email or password."
      : login.isError
        ? "Something went wrong. Please try again."
        : null;

  return (
    <div className="mx-auto max-w-sm">
      <div className="card">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          No account yet?{" "}
          <Link to="/signup" className="text-sky-700 underline dark:text-sky-400">
            Create one
          </Link>{" "}
          for free API access.
        </p>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            login.mutate();
          }}
        >
          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Email
            </label>
            <input
              type="email"
              required
              autoComplete="email"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Password
            </label>
            <input
              type="password"
              required
              autoComplete="current-password"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {errorMsg && <p className="text-sm text-red-600 dark:text-red-400">{errorMsg}</p>}
          <button
            type="submit"
            disabled={login.isPending}
            className="w-full rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
          >
            {login.isPending ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div className="mt-3 text-sm text-slate-500 dark:text-slate-400">
          {forgot.isSuccess ? (
            <p>{forgot.data.message}</p>
          ) : (
            <button
              type="button"
              className="text-sky-700 underline dark:text-sky-400 disabled:opacity-50"
              disabled={forgot.isPending || !email}
              title={email ? undefined : "Enter your email above first"}
              onClick={() => forgot.mutate()}
            >
              Forgot password?
            </button>
          )}
          {forgot.isError && (
            <p className="mt-1 text-red-600 dark:text-red-400">
              {forgot.error instanceof ApiError && forgot.error.status === 503
                ? "Password reset isn't available yet."
                : "Could not send the reset email. Try again later."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
