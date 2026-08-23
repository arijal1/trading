# Notifications (Phase 5, brief Sections 34/45)

`app/services/notifications/`. A `NotificationChannel` abstraction —
mirroring `ExchangeAdapter`'s pattern (`docs/EXCHANGE_ADAPTER.md`) — plus
a `NotificationService` that fans one event out to every configured
channel and persists an `alerts` row per attempt, whether or not delivery
actually succeeded. A failed Telegram send is itself visible in the audit
trail rather than silently swallowed.

## Channels

- **`LogNotificationChannel`** (`log_channel.py`) — writes to structured
  logs. Always "delivers" (it can't fail the way a network call can) and
  never depends on external configuration, so it's always included as the
  baseline channel.
- **`TelegramNotificationChannel`** (`telegram_channel.py`) — speaks the
  public Telegram Bot API's `sendMessage` method over HTTPS. Nothing
  scraped, no private/unofficial endpoints — the same Section 4 constraint
  that applies to exchange adapters applies here too. Requires
  `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`; network/API failures are
  caught and returned as a non-delivered `ChannelResult` rather than
  raised, so a Telegram outage can never take down a trading tick.

`build_default_notification_service(settings)` always includes the log
channel; Telegram is added only when *both* credentials are present — a
partially-configured deployment (token without chat id, or vice versa)
falls back to log-only rather than raising. No Telegram bot token exists
in this environment, so `TelegramNotificationChannel` is verified against
a mocked HTTP transport (`tests/unit/test_notification_channels.py`)
rather than a live bot.

## What fires a notification today

- `PaperTradingSession` (`docs/PAPER_TRADING.md`): `POSITION_OPENED`,
  `POSITION_EXIT` (title includes the exit trigger — stop-loss, trailing
  stop, take-profit, max-hold, trend-reversal, momentum-failure), and
  `CAPITAL_RECOVERED`.
- `system_state` (`docs/ARCHITECTURE.md`'s Section 40 kill switch):
  `EMERGENCY_STOP` (CRITICAL), `PAUSE_TRADING` (WARNING),
  `RESUME_TRADING` (INFO) — only when a `notification_service` is passed
  in; `GET/POST /trading/*` endpoints pass the real default service, but
  the underlying `system_state` functions default to `None` so existing
  callers/tests that don't care about notifications see no behavior
  change.

## Persistence

Every attempt — one row per channel, per event — is written to the
existing `alerts` table (`account_id`, `type`, `channel`, `payload`,
`sent_at`; see `docs/DATABASE_SCHEMA.md`). `payload` carries
`severity`/`title`/`body`/`delivered`/`error` plus whatever
event-specific fields the caller passed, since `alerts` has no dedicated
delivery-status column of its own.

## Scope (documented, not oversights)

- **No user-facing notification preferences.** Every configured channel
  receives every event; there's no per-user opt-in/opt-out or per-event-
  type routing yet (would need the auth/user-management work planned for
  Phase 5+).
- **No retry/backoff for a failed delivery.** A failed Telegram send is
  recorded and surfaced via `notifications_sent_total{delivered="false"}`
  (`docs/MONITORING.md`), not automatically retried.
- **No email/SMS/push channel.** Only log + Telegram exist; adding a
  channel means implementing `NotificationChannel` and registering it in
  `build_default_notification_service`.
