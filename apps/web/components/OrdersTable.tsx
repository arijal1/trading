import { formatDateTime, formatQuantity } from "@/lib/format";
import type { Order } from "@/lib/types";

const STATUS_COLOR: Record<string, string> = {
  FILLED: "text-emerald-700 dark:text-emerald-400",
  REJECTED: "text-red-700 dark:text-red-400",
  CANCELLED: "text-zinc-500 dark:text-zinc-400",
};

export default function OrdersTable({ orders }: { orders: Order[] }) {
  if (orders.length === 0) {
    return <p className="text-sm text-zinc-500">No orders yet.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="bg-zinc-100 text-xs uppercase text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th className="px-3 py-2">Side</th>
            <th className="px-3 py-2">Type</th>
            <th className="px-3 py-2">Quantity</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Error</th>
            <th className="px-3 py-2">Created</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id} className="border-t border-zinc-100 dark:border-zinc-800">
              <td className="px-3 py-2 font-medium">{o.side}</td>
              <td className="px-3 py-2">{o.type}</td>
              <td className="px-3 py-2">{formatQuantity(o.quantity)}</td>
              <td className={`px-3 py-2 ${STATUS_COLOR[o.status] ?? ""}`}>{o.status}</td>
              <td className="px-3 py-2 text-red-600 dark:text-red-400">
                {o.error ?? ""}
              </td>
              <td className="px-3 py-2 text-zinc-500 dark:text-zinc-400">
                {formatDateTime(o.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
