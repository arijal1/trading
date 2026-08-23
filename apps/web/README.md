# Trading Dashboard

Read/write Next.js dashboard for the paper-trading API in `apps/api`. See
`docs/DASHBOARD.md` at the repo root for scope, architecture, and what's
deliberately not built yet.

## Getting started

```bash
cp .env.example .env.local   # point NEXT_PUBLIC_API_BASE_URL at your API
npm install
npm run dev
```

Open http://localhost:3000. The API must be running separately (see the
root README) with `CORS_ALLOWED_ORIGINS` including this dashboard's origin
— the default `.env.example` values on both sides already match each
other for local development.

`npm run build` / `npm run lint` / `npx tsc --noEmit` are the checks this
project is verified against; there is no test suite yet (see
`docs/DASHBOARD.md`'s scope section).
