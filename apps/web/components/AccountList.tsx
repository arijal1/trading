"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { Account } from "@/lib/types";

export default function AccountList() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listAccounts()
      .then(setAccounts)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  if (error) {
    return <p className="text-sm text-red-600 dark:text-red-400">{error}</p>;
  }

  if (accounts === null) {
    return <p className="text-sm text-zinc-500">Loading accounts&hellip;</p>;
  }

  if (accounts.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No accounts yet. Accounts are created directly in the database for
        now (see docs/PAPER_TRADING.md) — there is no onboarding endpoint.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-zinc-100 text-xs uppercase text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">Mode</th>
            <th className="px-3 py-2">Starting equity</th>
            <th className="px-3 py-2">Created</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((a) => (
            <tr
              key={a.id}
              className="border-t border-zinc-100 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900"
            >
              <td className="px-3 py-2">
                <Link href={`/accounts/${a.id}`} className="font-medium hover:underline">
                  {a.name}
                </Link>
              </td>
              <td className="px-3 py-2">{a.mode}</td>
              <td className="px-3 py-2">
                {formatMoney(a.starting_equity, a.base_currency)}
              </td>
              <td className="px-3 py-2 text-zinc-500 dark:text-zinc-400">
                {formatDateTime(a.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
