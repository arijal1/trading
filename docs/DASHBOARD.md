# Dashboard (Phase 5, brief Section 43)

`apps/web` — Next.js 16 (App Router, TypeScript, Tailwind 4), scaffolded
with `create-next-app` and built out into a real client against the
Phase 1-5 API in `apps/api`. Read-only market/account views plus the two
write actions the brief calls for directly on the dashboard: the
emergency-stop/pause/resume kill switch and triggering a paper-trading
decision tick.

## Architecture

Every data fetch runs **client-side, in the browser** (`lib/api.ts`),
not through a Next.js server component or API route — there is no
backend-for-frontend layer. This is a deliberate simplicity choice for a
single internal dashboard talking to one backend, not an oversight:

- `NEXT_PUBLIC_API_BASE_URL` (baked in at build time — see
  `infrastructure/Dockerfile.web`) points the browser directly at
  `apps/api`.
- Every request passes `cache: "no-store"`. This dashboard shows live
  trading/risk state (equity, open positions, the kill-switch state)
  where a stale cached read is actively misleading, not just
  inconvenient — see `docs/RISK_MANAGEMENT.md`'s capital-preservation
  framing.
- The API's `CORSMiddleware` (`app/main.py`, `CORS_ALLOWED_ORIGINS`
  setting) is what makes this possible: a browser-origin request to a
  different origin is otherwise blocked by the browser itself, not by
  the API.

## Pages

- **`/`** — `SystemStatusPanel` (trading mode, DB connectivity,
  emergency-stop/halt state, with Emergency Stop / Pause / Resume
  buttons — each requires typing a reason, which is what the API audits
  against) and `AccountList` (every account, linking into its detail
  page).
- **`/accounts/[id]`** — `PortfolioSummary` (equity/cash/exposure/peak
  equity/drawdown tiles), `PaperTickPanel` (market + timeframe picker,
  "Run paper tick" button — only shown for `mode == "paper"` accounts),
  and `PositionsTable` / `OrdersTable` / `TradesTable`.

Money/quantity fields are typed as `string` end-to-end
(`lib/types.ts`) and only ever formatted for display
(`lib/format.ts`) — never parsed into `number` and used in arithmetic,
since the backend's `Decimal` guarantees don't survive a round-trip
through JS floats. The dashboard never computes a P&L or a risk figure
itself; every number it shows is a number the API already computed.

## Accounts have no onboarding UI

Matching the API's own scope note (`docs/API_DESIGN.md`,
`docs/PAPER_TRADING.md`): accounts are created directly in the database.
`GET /api/v1/accounts` (added alongside this dashboard, since a dashboard
that can't discover any accounts isn't useful) lists whatever exists;
there is no "create account" form.

## Verification

No automated test suite exists yet for this app (see Scope below).
Verified instead via:

- `npm run build`, `npm run lint` (ESLint, including the new
  React-Compiler-derived hook rules — see the `set-state-in-effect`
  note below), and `npx tsc --noEmit`, all clean.
- A live end-to-end pass against a running `apps/api` instance and real
  Postgres: seeded an account/market/position via SQL, loaded both pages
  in a real Chromium browser via Playwright, and exercised every
  interactive control — clicking "Run paper tick" (which correctly hit
  the seeded position's stop-loss and closed it, live, in the UI) and
  Emergency Stop / Resume (prompt → API call → UI flips to the red/green
  banner and back).

### A real Next.js 16 dev-server gotcha, not a dashboard bug

The dev server's `next dev` treats `127.0.0.1` and `localhost` as
different origins by default (`allowedDevOrigins`) and returns `403` on
the JS chunk requests for a cross-origin page load, which silently
prevents hydration — the page stays on its server-rendered "Loading…"
state forever with no console error pointing at the cause. Access the
dev server via the same hostname consistently (`localhost` throughout,
or configure `allowedDevOrigins` in `next.config.ts`) — this only
affects `next dev`, not the production build.

### `react-hooks/set-state-in-effect`

`eslint-config-next`'s new React-Compiler-derived rule set flags any
Effect that can reach a `setState` call — including through
`useEffectEvent`, React's own documented escape hatch for "fetch on
mount" (see `SystemStatusPanel.tsx` and `app/accounts/[id]/page.tsx`).
This is treated here as a rough edge in a brand-new lint rule, not a
real problem with the pattern (which is the standard, React-team-
documented way to fetch data on mount), and silenced with a scoped
`eslint-disable-next-line` plus a comment at each site — not disabled
project-wide, and not worked around with a worse pattern.

## Scope (documented, not oversights)

- **No test suite.** Unlike every backend phase, this app has no
  automated tests yet — verification was manual/live (build, lint,
  typecheck, and a real browser pass) rather than `npm test`. Worth
  adding (Playwright or Vitest + Testing Library) once the dashboard's
  surface area grows past what a manual pass can cover confidently.
- **No auth.** Matches the API's own Phase 1-5 posture (`docs/
  API_DESIGN.md`: "Auth lands in Phase 5+") — anyone who can reach the
  dashboard can reach every account and can trip the kill switch.
  Acceptable for an internal/local tool talking to a paper-trading
  backend; not acceptable to expose past a trusted network as-is.
- **No `/signals`, `/decisions`, `/traders`, `/copy-trading` views.**
  Those API endpoints don't exist yet either (`docs/API_DESIGN.md`'s
  "Planned" table) — nothing to build a view against.
- **No polling/auto-refresh.** Every page loads once and after an
  action; there's no live-updating ticker. A real deployment ticking
  markets on a schedule (Phase 5+ background worker, per
  `docs/ARCHITECTURE.md`) would want one.
- **`window.prompt`/`window.confirm` for the risky actions**, not a
  proper modal component. Deliberately unmissable and blocking — fine
  for an internal tool's kill switch, not a pattern to reuse for
  anything less consequential.
