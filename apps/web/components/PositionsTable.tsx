import { formatDateTime, formatMoney, formatQuantity } from "@/lib/format";
import type { Position } from "@/lib/types";

const STATUS_COLOR: Record<string, string> = {
  OPEN: "text-emerald-700 dark:text-emerald-400",
  PROFIT_RUNNER: "text-emerald-700 dark:text-emerald-400",
  CLOSED: "text-zinc-500 dark:text-zinc-400",
};

export default function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <p className="text-sm text-zinc-500">No positions yet.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="bg-zinc-100 text-xs uppercase text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Quantity</th>
            <th className="px-3 py-2">Avg entry</th>
            <th className="px-3 py-2">Stop</th>
            <th className="px-3 py-2">Take profit</th>
            <th className="px-3 py-2">Capital recovered</th>
            <th className="px-3 py-2">Profit locked</th>
            <th className="px-3 py-2">Opened</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr
              key={p.id}
              className="border-t border-zinc-100 dark:border-zinc-800"
            >
              <td className={`px-3 py-2 font-medium ${STATUS_COLOR[p.status] ?? ""}`}>
                {p.status}
              </td>
              <td className="px-3 py-2">{formatQuantity(p.quantity)}</td>
              <td className="px-3 py-2">{formatMoney(p.avg_entry_price)}</td>
              <td className="px-3 py-2">
                {p.stop_price ? formatMoney(p.stop_price) : "—"}
              </td>
              <td className="px-3 py-2">
                {p.take_profit_price ? formatMoney(p.take_profit_price) : "—"}
              </td>
              <td className="px-3 py-2">{formatMoney(p.capital_recovered)}</td>
              <td className="px-3 py-2">{formatMoney(p.profit_locked)}</td>
              <td className="px-3 py-2 text-zinc-500 dark:text-zinc-400">
                {formatDateTime(p.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
