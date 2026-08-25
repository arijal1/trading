"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Market, TickResult } from "@/lib/types";

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

function countActions(results: TickResult[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const r of results) counts.set(r.action, (counts.get(r.action) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

const ACTION_COLOR: Record<string, string> = {
  OPENED: "text-emerald-700 dark:text-emerald-400",
  EXIT: "text-amber-700 dark:text-amber-400",
  CAPITAL_RECOVERED: "text-emerald-700 dark:text-emerald-400",
};

export default function PaperTickPanel({
  accountId,
  onTick,
  timeframe,
  onTimeframeChange,
}: {
  accountId: string;
  onTick: () => void;
  timeframe: string;
  onTimeframeChange: (tf: string) => void;
}) {
  const [markets, setMarkets] = useState<Market[] | null>(null);
  const [marketId, setMarketId] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TickResult | null>(null);
  const [history, setHistory] = useState<TickResult[]>([]);
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

  // One tick is one decision, and most decisions are HOLD. Clicking once
  // and seeing HOLD reads as "nothing works"; running a batch is what
  // makes the strategy's behaviour visible, because entries only appear
  // as the simulated clock advances across bars.
  async function runTicks(count: number) {
    if (!marketId) return;
    setRunning(true);
    setError(null);
    const collected: TickResult[] = [];
    try {
      for (let i = 0; i < count; i++) {
        const response = await api.runPaperTick(accountId, marketId, timeframe);
        collected.push(response.result);
        // Stop early on a state that repeating cannot fix — otherwise a
        // batch of 25 just prints INSUFFICIENT_DATA 25 times.
        if (response.result.action === "INSUFFICIENT_DATA") break;
      }
      setHistory(collected);
      setResult(collected[collected.length - 1] ?? null);
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
          onChange={(e) => onTimeframeChange(e.target.value)}
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
          onClick={() => runTicks(1)}
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {running ? "Running…" : "Run one tick"}
        </button>
        <button
          type="button"
          disabled={running || !marketId}
          onClick={() => runTicks(25)}
          className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          {running ? "Running…" : "Run 25 ticks"}
        </button>
      </div>

      {error && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>
      )}
      {result && (
        <div className="mt-3 text-sm">
          <p>
            <span className={`font-semibold ${ACTION_COLOR[result.action] ?? ""}`}>
              {result.action}
            </span>
            {" — "}
            <span className="text-zinc-600 dark:text-zinc-400">{result.detail}</span>
          </p>

          {result.action === "INSUFFICIENT_DATA" && (
            <p className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
              There is not enough price history for this market and
              timeframe yet. Use <strong>Load price history</strong> above,
              then run the ticks again.
            </p>
          )}

          {history.length > 1 && (
            <div className="mt-3">
              <p className="text-xs text-zinc-500">
                {history.length} ticks — what the strategy decided:
              </p>
              <ul className="mt-1 flex flex-wrap gap-1">
                {countActions(history).map(([action, n]) => (
                  <li
                    key={action}
                    className={`rounded-md border border-zinc-200 px-2 py-0.5 text-xs dark:border-zinc-700 ${
                      ACTION_COLOR[action] ?? "text-zinc-600 dark:text-zinc-400"
                    }`}
                  >
                    {action} &times;{n}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                Mostly HOLD is normal and intended — the strategy declines
                far more often than it trades. Capital preservation first.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
