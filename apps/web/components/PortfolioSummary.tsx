"use client";

import { formatMoney, formatPercent } from "@/lib/format";
import type { PortfolioState } from "@/lib/types";

function drawdownFraction(state: PortfolioState): string {
  const peak = Number(state.peak_equity);
  const equity = Number(state.equity);
  if (!(peak > 0)) return "0";
  return String(Math.max(0, (peak - equity) / peak));
}

export default function PortfolioSummary({ state }: { state: PortfolioState }) {
  const tiles: { label: string; value: string }[] = [
    { label: "Equity", value: formatMoney(state.equity) },
    { label: "Cash", value: formatMoney(state.cash) },
    { label: "Exposure", value: formatMoney(state.total_exposure) },
    { label: "Open positions", value: String(state.open_position_count) },
    { label: "Peak equity", value: formatMoney(state.peak_equity) },
    { label: "Drawdown", value: formatPercent(drawdownFraction(state)) },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-6">
      {tiles.map((tile) => (
        <div
          key={tile.label}
          className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
        >
          <div className="text-xs text-zinc-500 dark:text-zinc-400">{tile.label}</div>
          <div className="mt-1 text-sm font-semibold">{tile.value}</div>
        </div>
      ))}
      {(state.is_emergency_stopped || state.is_trading_halted) && (
        <div className="col-span-full rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {state.is_emergency_stopped
            ? "Emergency stop is active account-wide."
            : "Trading is currently halted account-wide."}
        </div>
      )}
    </div>
  );
}
