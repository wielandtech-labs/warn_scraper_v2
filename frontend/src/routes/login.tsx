import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { api, ApiError } from "../api/client";

export function LoginPage() {
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
        <p className="mt-1 text-sm text-slate-500">
          Accounts are issued by the site operator.
        </p>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            login.mutate();
          }}
        >
          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Email
            </label>
            <input
              type="email"
              required
              autoComplete="email"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Password
            </label>
            <input
              type="password"
              required
              autoComplete="current-password"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {errorMsg && <p className="text-sm text-red-600">{errorMsg}</p>}
          <button
            type="submit"
            disabled={login.isPending}
            className="w-full rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
          >
            {login.isPending ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
