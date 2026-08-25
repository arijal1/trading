// Thin fetch wrapper around the trading-api backend. No caching layer of
// its own — every call is `cache: "no-store"` since this dashboard shows
// live trading/risk state, where a stale read is actively misleading
// (see docs/RISK_MANAGEMENT.md's "capital preservation first" framing).

import { getToken, setToken } from "./auth";
import type {
  Account,
  AuthConfig,
  Candle,
  Market,
  Order,
  PaperTickResponse,
  PortfolioState,
  Position,
  SystemState,
  SyncResult,
  SystemStatus,
  TokenResponse,
  Trade,
  User,
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
  const token = getToken();
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    // A 401 on a request that *carried* a token means the token is no
    // longer good — expired, or the user was deactivated server-side
    // (deps.py re-checks is_active on every request, so revocation is
    // immediate). Drop it so the app falls back to the login screen
    // instead of retrying forever with a dead credential.
    //
    // Guarded on `token` because a 401 from /auth/login is a wrong
    // password, not a stale session, and clearing there would be
    // meaningless churn.
    if (response.status === 401 && token) {
      setToken(null);
    }
    const body = await response.text();
    throw new ApiError(response.status, body || response.statusText);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  // Public — answerable before any credential exists.
  authConfig: () => request<AuthConfig>("/api/v1/auth/config"),
  login: (email: string, password: string) =>
    request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/api/v1/auth/me"),

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

  // Loading price history is a prerequisite for every strategy decision:
  // with fewer than ~35 bars a tick can only answer INSUFFICIENT_DATA.
  // It had no UI at all, so the dashboard's one action was guaranteed to
  // do nothing until the user found the right curl command in the docs.
  syncCandles: (marketId: string, timeframe: string, hours: number) =>
    request<SyncResult>(
      `/api/v1/markets/${marketId}/sync?timeframe=${timeframe}&hours=${hours}`,
      { method: "POST" }
    ),
  listCandles: (marketId: string, timeframe: string, limit = 1000) =>
    request<Candle[]>(
      `/api/v1/markets/${marketId}/candles?timeframe=${timeframe}&limit=${limit}`
    ),
};
