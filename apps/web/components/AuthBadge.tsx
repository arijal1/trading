"use client";

import { useAuth } from "./AuthProvider";

/** Header strip showing who you are — or that nobody has to be anybody. */
export default function AuthBadge() {
  const { status, user, logout } = useAuth();

  if (status === "open") {
    return (
      <span
        className="rounded-md border border-amber-400 bg-amber-50 px-2 py-1 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
        title="AUTH_REQUIRED=false: every API caller is treated as anonymous. Fine on a trusted LAN; do not expose this to the internet."
      >
        Unauthenticated mode
      </span>
    );
  }

  if (status !== "authenticated" || user === null) return null;

  return (
    <span className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
      <span className="truncate">
        {user.email}
        {user.role === "admin" ? " (admin)" : ""}
      </span>
      <button
        type="button"
        onClick={logout}
        className="rounded-md border border-zinc-300 px-2 py-1 font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
      >
        Sign out
      </button>
    </span>
  );
}
