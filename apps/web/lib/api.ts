// Thin fetch wrapper around the trading-api backend. No caching layer of
// its own — every call is `cache: "no-store"` since this dashboard shows
// live trading/risk state, where a stale read is actively misleading
// (see docs/RISK_MANAGEMENT.md's "capital preservation first" framing).

import type {
  Account,
  Market,
  Order,
  PaperTickResponse,
  PortfolioState,
  Position,
  SystemState,
  SystemStatus,
  Trade,
} from "./types";

export function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(response.status, body || response.statusText);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  systemStatus: () => request<SystemStatus>("/api/v1/system/status"),
  emergencyStop: (reason: string, actor: string) =>
    request<SystemState>("/api/v1/trading/emergency-stop", {
      method: "POST",
      body: JSON.stringify({ reason, actor }),
    }),
  resumeTrading: (reason: string, actor: string) =>
    request<SystemState>("/api/v1/trading/resume", {
      method: "POST",
      body: JSON.stringify({ reason, actor }),
    }),
  pauseTrading: (reason: string, actor: string) =>
    request<SystemState>("/api/v1/trading/pause", {
      method: "POST",
      body: JSON.stringify({ reason, actor }),
    }),

  listAccounts: () => request<Account[]>("/api/v1/accounts"),
  getAccount: (id: string) => request<Account>(`/api/v1/accounts/${id}`),
  getPortfolio: (id: string) =>
    request<PortfolioState>(`/api/v1/accounts/${id}/portfolio`),
  listPositions: (id: string) =>
    request<Position[]>(`/api/v1/accounts/${id}/positions`),
  listOrders: (id: string) => request<Order[]>(`/api/v1/accounts/${id}/orders`),
  listTrades: (id: string) => request<Trade[]>(`/api/v1/accounts/${id}/trades`),
  runPaperTick: (id: string, marketId: string, timeframe: string) =>
    request<PaperTickResponse>(`/api/v1/accounts/${id}/paper/tick`, {
      method: "POST",
      body: JSON.stringify({ market_id: marketId, timeframe }),
    }),

  listMarkets: () => request<Market[]>("/api/v1/markets"),
};
