"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Market, TickResult } from "@/lib/types";

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

const ACTION_COLOR: Record<string, string> = {
  OPENED: "text-emerald-700 dark:text-emerald-400",
  EXIT: "text-amber-700 dark:text-amber-400",
  CAPITAL_RECOVERED: "text-emerald-700 dark:text-emerald-400",
};

export default function PaperTickPanel({
  accountId,
  onTick,
}: {
  accountId: string;
  onTick: () => void;
}) {
  const [markets, setMarkets] = useState<Market[] | null>(null);
  const [marketId, setMarketId] = useState("");
  const [timeframe, setTimeframe] = useState("1h");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TickResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listMarkets()
      .then((m) => {
        setMarkets(m);
        if (m.length > 0) setMarketId(m[0].id);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  async function runTick() {
    if (!marketId) return;
    setRunning(true);
    setError(null);
    try {
      const response = await api.runPaperTick(accountId, marketId, timeframe);
      setResult(response.result);
      onTick();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={marketId}
          onChange={(e) => setMarketId(e.target.value)}
          className="rounded-md border border-zinc-300 bg-transparent px-2 py-1.5 text-sm dark:border-zinc-700"
        >
          {markets === null && <option>Loading markets&hellip;</option>}
          {markets?.length === 0 && <option>No markets configured</option>}
          {markets?.map((m) => (
            <option key={m.id} value={m.id}>
              {m.symbol} ({m.exchange_name})
            </option>
          ))}
        </select>
        <select
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
          className="rounded-md border border-zinc-300 bg-transparent px-2 py-1.5 text-sm dark:border-zinc-700"
        >
          {TIMEFRAMES.map((tf) => (
            <option key={tf} value={tf}>
              {tf}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={running || !marketId}
          onClick={runTick}
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {running ? "Running…" : "Run paper tick"}
        </button>
      </div>

      {error && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>
      )}
      {result && (
        <p className="mt-3 text-sm">
          <span className={`font-semibold ${ACTION_COLOR[result.action] ?? ""}`}>
            {result.action}
          </span>
          {" — "}
          <span className="text-zinc-600 dark:text-zinc-400">{result.detail}</span>
        </p>
      )}
    </div>
  );
}
