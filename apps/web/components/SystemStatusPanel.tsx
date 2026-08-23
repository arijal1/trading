"use client";

import { useEffect, useEffectEvent, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { SystemStatus } from "@/lib/types";

const ACTOR = "dashboard";

type PendingAction = "stop" | "pause" | "resume" | null;

export default function SystemStatusPanel() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction>(null);

  async function refresh() {
    try {
      const s = await api.systemStatus();
      setStatus(s);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  // useEffectEvent (React 19.2 / Next 16) rather than a plain
  // useCallback+useEffect pair: `refresh` is also called directly from
  // the button handlers below (not just on mount), so it can't be a
  // reactive Effect dependency — this is exactly the "non-reactive logic
  // called from an Effect" case the hook exists for. The `set-state-in-
  // effect` rule still flags calling it here — as of React 19.2/eslint-
  // plugin-react-hooks's new Compiler-derived rules, it flags *any*
  // effect that reaches a setState call, including through the
  // useEffectEvent escape hatch React's own docs recommend for this
  // exact "fetch on mount" case. Silencing deliberately, not working
  // around it with a worse pattern.
  const onMount = useEffectEvent(refresh);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    onMount();
  }, []);

  async function act(action: Exclude<PendingAction, null>, confirmMessage: string) {
    const reason = window.prompt(
      `${confirmMessage}\n\nEnter a reason (required, gets audited):`
    );
    if (!reason) return;
    setPending(action);
    try {
      if (action === "stop") await api.emergencyStop(reason, ACTOR);
      if (action === "pause") await api.pauseTrading(reason, ACTOR);
      if (action === "resume") await api.resumeTrading(reason, ACTOR);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setPending(null);
    }
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
        Could not reach the trading API: {error}
      </div>
    );
  }

  if (!status) {
    return (
      <div className="rounded-lg border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800">
        Loading system status&hellip;
      </div>
    );
  }

  const stopped = status.is_emergency_stopped;
  const halted = status.is_trading_halted;

  return (
    <div
      className={`rounded-lg border p-4 ${
        stopped
          ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950"
          : halted
            ? "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950"
            : "border-emerald-300 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">
            {stopped
              ? "EMERGENCY STOP ACTIVE"
              : halted
                ? "Trading paused"
                : "Trading live (paper mode)"}
          </div>
          <div className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
            mode={status.trading_mode} &middot; db=
            {status.database_connected ? "connected" : "disconnected"}
            {status.reason ? ` — ${status.reason}` : ""}
          </div>
        </div>
        <div className="flex gap-2">
          {!stopped && (
            <button
              type="button"
              disabled={pending !== null}
              onClick={() =>
                act(
                  "stop",
                  "This immediately halts all paper trading and requires a manual resume."
                )
              }
              className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              Emergency Stop
            </button>
          )}
          {!stopped && !halted && (
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => act("pause", "This pauses trading (no forced position closure).")}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              Pause
            </button>
          )}
          {(stopped || halted) && (
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => act("resume", "This resumes trading.")}
              className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Resume
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
