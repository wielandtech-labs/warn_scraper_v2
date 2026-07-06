import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api, ApiError } from "../api/client";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

const INPUT_CLS =
  "mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const LABEL_CLS =
  "text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400";

export function SignupPage() {
  useDocumentTitle("Create account — WARN Tracker");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const signup = useMutation({
    mutationFn: () => api.signup(email, password),
  });

  const errorMsg =
    signup.error instanceof ApiError && signup.error.status === 503
      ? "Signup isn't open yet — check back soon."
      : signup.error instanceof ApiError && signup.error.status === 429
        ? "Too many attempts from your network; try again later."
        : signup.error instanceof ApiError && signup.error.status === 422
          ? "Enter a valid email and a password of at least 12 characters."
          : signup.isError
            ? "Something went wrong. Please try again."
            : null;

  if (signup.isSuccess) {
    return (
      <div className="mx-auto max-w-sm">
        <div className="card">
          <h1 className="text-xl font-semibold">Check your email</h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            {signup.data.message} Click the link inside to activate your account,
            then <Link to="/login" className="text-sky-700 underline dark:text-sky-400">sign in</Link>{" "}
            to create API keys.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-sm">
      <div className="card">
        <h1 className="text-xl font-semibold">Create an account</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Free API access with your own keys. See{" "}
          <Link to="/api-docs" className="text-sky-700 underline dark:text-sky-400">
            Data &amp; API
          </Link>{" "}
          for tiers and limits.
        </p>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            signup.mutate();
          }}
        >
          <div>
            <label className={LABEL_CLS}>Email</label>
            <input
              type="email"
              required
              autoComplete="email"
              className={INPUT_CLS}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className={LABEL_CLS}>Password</label>
            <input
              type="password"
              required
              minLength={12}
              autoComplete="new-password"
              className={INPUT_CLS}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              At least 12 characters.
            </p>
          </div>
          {errorMsg && <p className="text-sm text-red-600 dark:text-red-400">{errorMsg}</p>}
          <button
            type="submit"
            disabled={signup.isPending}
            className="w-full rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
          >
            {signup.isPending ? "Creating…" : "Create account"}
          </button>
        </form>
        <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">
          Already have an account?{" "}
          <Link to="/login" className="text-sky-700 underline dark:text-sky-400">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
