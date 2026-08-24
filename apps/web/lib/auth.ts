// Bearer-token storage for the dashboard.
//
// The token lives in localStorage. That is a deliberate trade-off worth
// stating plainly rather than burying:
//
//   - The API issues a bearer JWT and reads it from the Authorization
//     header (app/api/deps.py). There is no cookie session to piggyback
//     on, and adding one would mean credentialed CORS plus CSRF defence
//     for a dashboard that is a different origin from the API.
//   - localStorage is readable by any script running on this origin, so
//     an XSS bug here is a token theft. The mitigations are that the
//     dashboard loads no third-party scripts, and that JWT_EXPIRE_MINUTES
//     defaults to 60 — a stolen token expires, and disabling the user in
//     the DB revokes it immediately (deps.py re-checks is_active on every
//     request, it does not trust the token alone).
//
// If this is ever exposed to the open internet, put it behind a reverse
// proxy with TLS; a bearer token over plain HTTP is readable in transit
// regardless of where the browser keeps it. See docs/AUTH.md.

const STORAGE_KEY = "trading-dashboard-token";

// Module-level mirror so reads work during render on the client without
// touching localStorage every time, and so the very first render after a
// login already sees the new value.
let cached: string | null = null;
let loaded = false;

type Listener = () => void;
const listeners = new Set<Listener>();

export function getToken(): string | null {
  // Server-rendered pass: there is no localStorage, and returning null is
  // correct — the server never holds the user's credential.
  if (typeof window === "undefined") return null;
  if (!loaded) {
    try {
      cached = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      // Private-mode / blocked storage. Sessions just won't persist
      // across reloads; that is degraded, not broken.
      cached = null;
    }
    loaded = true;
  }
  return cached;
}

export function setToken(token: string | null): void {
  cached = token;
  loaded = true;
  if (typeof window !== "undefined") {
    try {
      if (token === null) window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, token);
    } catch {
      // Ignore: `cached` still holds it for this tab's lifetime.
    }
  }
  for (const listener of listeners) listener();
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
