import { formatDateTime, formatMoney, formatQuantity } from "@/lib/format";
import type { Trade } from "@/lib/types";

export default function TradesTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return <p className="text-sm text-zinc-500">No fills yet.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="bg-zinc-100 text-xs uppercase text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th className="px-3 py-2">Price</th>
            <th className="px-3 py-2">Quantity</th>
            <th className="px-3 py-2">Fee</th>
            <th className="px-3 py-2">Filled</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id} className="border-t border-zinc-100 dark:border-zinc-800">
              <td className="px-3 py-2">{formatMoney(t.price)}</td>
              <td className="px-3 py-2">{formatQuantity(t.quantity)}</td>
              <td className="px-3 py-2">{formatMoney(t.fee)}</td>
              <td className="px-3 py-2 text-zinc-500 dark:text-zinc-400">
                {formatDateTime(t.filled_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
