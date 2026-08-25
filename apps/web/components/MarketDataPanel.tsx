"use client";

import { useEffect, useEffectEvent, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Market } from "@/lib/types";

// 35 is the real threshold: the slowest indicator in the entry strategy
// needs that many closed bars before it produces a value, and below it
// every tick can only answer INSUFFICIENT_DATA. Surfaced here so an empty
// chart explains itself instead of looking like a broken dashboard.
const MIN_BARS = 35;
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

interface Row {
  market: Market;
  bars: number | null;
}

export default function MarketDataPanel({
  timeframe,
  onTimeframeChange,
}: {
  timeframe: string;
  onTimeframeChange: (tf: string) => void;
}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function refresh() {
    try {
      const markets = await api.listMarkets();
      const counted = await Promise.all(
        markets.map(async (market) => {
          try {
            const candles = await api.listCandles(market.id, timeframe);
            return { market, bars: candles.length };
          } catch {
            // One market failing to report must not blank the whole
            // panel — show the rest and mark this one unknown.
            return { market, bars: null };
          }
        })
      );
      setRows(counted);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const reload = useEffectEvent(refresh);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
  }, [timeframe]);

  async function load(market: Market) {
    setBusy(market.id);
    setError(null);
    setNote(null);
    try {
      // 400 hours of hourly bars comfortably clears MIN_BARS with room
      // for the strategy to see a trend rather than just enough to
      // compute one value.
      const result = await api.syncCandles(market.id, timeframe, 400);
      setNote(
        `${market.symbol}: ${result.inserted_count} new bars stored ` +
          `(${result.already_stored_count} already there` +
          `${result.gap_count > 0 ? `, ${result.gap_count} gaps` : ""}).`
      );
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Price history the strategy can see. It needs at least{" "}
          <strong>{MIN_BARS} bars</strong> before it will evaluate anything.
        </p>
        <label className="flex items-center gap-2 text-xs">
          <span className="text-zinc-500">Timeframe</span>
          <select
            value={timeframe}
            onChange={(e) => onTimeframeChange(e.target.value)}
            className="rounded-md border border-zinc-300 bg-transparent px-2 py-1 dark:border-zinc-700"
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {error}
        </p>
      )}
      {note && (
        <p className="mt-3 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
          {note}
        </p>
      )}

      {rows === null ? (
        <p className="mt-3 text-sm text-zinc-500">Loading markets&hellip;</p>
      ) : rows.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-500">
          No markets yet. Seed the demo data:{" "}
          <code>bash scripts/local.sh logs api</code> if this looks wrong.
        </p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {rows.map(({ market, bars }) => {
            const ready = bars !== null && bars >= MIN_BARS;
            return (
              <li
                key={market.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-zinc-100 px-3 py-2 dark:border-zinc-800"
              >
                <div className="text-sm">
                  <span className="font-medium">{market.symbol}</span>{" "}
                  <span className="text-xs text-zinc-500">
                    {market.exchange_name}
                  </span>
                  <div className="text-xs">
                    {bars === null ? (
                      <span className="text-zinc-500">bar count unavailable</span>
                    ) : ready ? (
                      <span className="text-emerald-700 dark:text-emerald-400">
                        {bars} bars — ready to trade
                      </span>
                    ) : (
                      <span className="text-amber-700 dark:text-amber-400">
                        {bars} bars — needs {MIN_BARS - bars} more
                      </span>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => load(market)}
                  className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                >
                  {busy === market.id ? "Loading…" : "Load price history"}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
        These prices are <strong>synthetic</strong> — generated by the mock
        exchange adapter, not a real venue. The strategy and risk logic are
        real; the market they are reading is not.
      </p>
    </div>
  );
}
