"use client";

import Link from "next/link";
import { use, useEffect, useEffectEvent, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import OrdersTable from "@/components/OrdersTable";
import PaperTickPanel from "@/components/PaperTickPanel";
import PortfolioSummary from "@/components/PortfolioSummary";
import PositionsTable from "@/components/PositionsTable";
import TradesTable from "@/components/TradesTable";
import type { Account, Order, PortfolioState, Position, Trade } from "@/lib/types";

interface AccountData {
  account: Account;
  portfolio: PortfolioState;
  positions: Position[];
  orders: Order[];
  trades: Trade[];
}

export default function AccountPage({ params }: PageProps<"/accounts/[id]">) {
  const { id } = use(params);
  const [data, setData] = useState<AccountData | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [account, portfolio, positions, orders, trades] = await Promise.all([
        api.getAccount(id),
        api.getPortfolio(id),
        api.listPositions(id),
        api.listOrders(id),
        api.listTrades(id),
      ]);
      setData({ account, portfolio, positions, orders, trades });
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  // See SystemStatusPanel's comment: useEffectEvent for the mount-time
  // load since `load` is also called directly from PaperTickPanel's
  // onTick handler, not just here; the `set-state-in-effect` lint rule
  // is silenced deliberately, not worked around.
  const onMount = useEffectEvent(load);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    onMount();
  }, [id]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
        {error}
      </div>
    );
  }

  if (!data) {
    return <p className="text-sm text-zinc-500">Loading account&hellip;</p>;
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link href="/" className="text-xs text-zinc-500 hover:underline">
          &larr; All accounts
        </Link>
        <h1 className="mt-1 text-lg font-semibold">
          {data.account.name}{" "}
          <span className="text-sm font-normal text-zinc-500">
            ({data.account.mode}, starting equity{" "}
            {formatMoney(data.account.starting_equity, data.account.base_currency)})
          </span>
        </h1>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-500">Portfolio</h2>
        <PortfolioSummary state={data.portfolio} />
      </section>

      {data.account.mode === "paper" && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-zinc-500">
            Run a paper-trading tick
          </h2>
          <PaperTickPanel accountId={id} onTick={load} />
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-500">Positions</h2>
        <PositionsTable positions={data.positions} />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-500">Orders</h2>
        <OrdersTable orders={data.orders} />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-zinc-500">Trades</h2>
        <TradesTable trades={data.trades} />
      </section>
    </div>
  );
}
