"use client";

import type { ReactNode } from "react";
import LoginForm from "./LoginForm";
import { useAuth } from "./AuthProvider";

/** Renders the dashboard only once we know the caller is allowed to see it. */
export default function AuthGate({ children }: { children: ReactNode }) {
  const { status, error, retry } = useAuth();

  if (status === "loading") {
    return <p className="py-10 text-center text-sm text-zinc-500">Loading&hellip;</p>;
  }

  if (status === "unreachable") {
    return (
      <div className="mx-auto max-w-md py-10 text-center">
        <p className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          Could not reach the trading API.
          {error ? <span className="block break-all pt-2 font-mono text-xs">{error}</span> : null}
        </p>
        <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
          This is not a login problem — the API did not answer at all. See
          <code> docs/TROUBLESHOOTING.md</code>.
        </p>
        <button
          type="button"
          onClick={retry}
          className="mt-4 rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Retry
        </button>
      </div>
    );
  }

  if (status === "anonymous") {
    return <LoginForm />;
  }

  // "open" (AUTH_REQUIRED=false) and "authenticated" both render the app.
  // The banner in the header is what distinguishes them, so an unguarded
  // deployment is visible rather than silent.
  return <>{children}</>;
}
