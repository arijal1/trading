// Mirrors the Pydantic response models in apps/api/app/schemas/*.py.
// Decimal/UUID/datetime fields all serialize to strings over JSON, so
// they're typed as `string` here and formatted at render time rather than
// parsed into `number`/`Date` — money must stay exact, and this dashboard
// never does arithmetic on these values itself, only displays them.

export interface SystemStatus {
  status: string;
  trading_mode: string;
  database_connected: boolean;
  is_emergency_stopped: boolean;
  is_trading_halted: boolean;
  reason: string | null;
}

export interface SystemState {
  is_emergency_stopped: boolean;
  is_trading_halted: boolean;
  reason: string | null;
  set_by: string | null;
  set_at: string | null;
}

export interface Account {
  id: string;
  user_id: string;
  name: string;
  mode: string;
  base_currency: string;
  starting_equity: string;
  created_at: string;
}

export interface PortfolioState {
  equity: string;
  cash: string;
  open_position_count: number;
  exposure_by_asset: Record<string, string>;
  total_exposure: string;
  peak_equity: string;
  day_start_equity: string;
  week_start_equity: string;
  is_emergency_stopped: boolean;
  is_trading_halted: boolean;
}

export interface Position {
  id: string;
  asset_id: string;
  status: string;
  initial_capital: string;
  quantity: string;
  avg_entry_price: string;
  capital_recovered: string;
  profit_locked: string;
  stop_price: string | null;
  take_profit_price: string | null;
  trailing_stop_pct: string | null;
  highest_price_since_entry: string | null;
  created_at: string;
  updated_at: string;
}

export interface Order {
  id: string;
  client_order_id: string;
  exchange_order_id: string | null;
  asset_id: string;
  side: string;
  type: string;
  quantity: string;
  limit_price: string | null;
  status: string;
  error: string | null;
  created_at: string;
}

export interface Trade {
  id: string;
  order_id: string;
  price: string;
  quantity: string;
  fee: string;
  slippage: string | null;
  filled_at: string;
}

export interface Market {
  id: string;
  exchange_id: string;
  exchange_name: string;
  symbol: string;
  base_asset_symbol: string;
  quote_asset_symbol: string;
}

export type TickAction =
  | "OPENED"
  | "EXIT"
  | "CAPITAL_RECOVERED"
  | "HOLD"
  | "SKIPPED_RISK"
  | "SKIPPED_SIZE"
  | "NO_SIGNAL"
  | "INSUFFICIENT_DATA";

export interface TickResult {
  action: TickAction;
  detail: string;
  order_id: string | null;
  position_id: string | null;
}

export interface PaperTickResponse {
  result: TickResult;
}

// --- auth (docs/AUTH.md) ---

export interface AuthConfig {
  auth_required: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
}

export interface User {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
}

export interface SyncResult {
  requested_count: number;
  already_stored_count: number;
  fetched_count: number;
  inserted_count: number;
  gap_count: number;
  adapter_called: boolean;
}

export interface Candle {
  ts: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}
