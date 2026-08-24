"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "@/lib/api";
import { getToken, setToken, subscribe } from "@/lib/auth";
import type { User } from "@/lib/types";

// Four honestly-distinct states. Collapsing "we haven't asked yet" into
// "logged out" is what makes dashboards flash a login screen on every
// reload, and collapsing "the API is unreachable" into "logged out" sends
// people hunting for a password problem when the backend is simply down.
type Status =
  | "loading"
  | "open" // AUTH_REQUIRED=false — no login needed
  | "anonymous" // auth required, no valid token
  | "authenticated"
  | "unreachable"; // couldn't ask; not a credential problem

interface AuthState {
  status: Status;
  user: User | null;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  retry: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  const resolve = useCallback(async () => {
    setStatus("loading");
    setError(null);
    let required: boolean;
    try {
      required = (await api.authConfig()).auth_required;
    } catch (err) {
      // /auth/config is public, so a failure here is a transport or
      // server problem, never an authorization one.
      setStatus("unreachable");
      setError(err instanceof ApiError ? err.message : String(err));
      return;
    }

    if (!required) {
      setUser(null);
      setStatus("open");
      return;
    }

    if (getToken() === null) {
      setStatus("anonymous");
      return;
    }

    try {
      setUser(await api.me());
      setStatus("authenticated");
    } catch (err) {
      // request() has already discarded the dead token on a 401.
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
        setStatus("anonymous");
        return;
      }
      setStatus("unreachable");
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void resolve();
  }, [resolve]);

  // Any part of the app can invalidate the session simply by making a
  // request that 401s — request() clears the token, which fires this.
  // Without it a stale tab keeps rendering panels that all fail
  // individually instead of returning to the login screen once.
  useEffect(
    () =>
      subscribe(() => {
        if (getToken() === null) {
          setUser(null);
          setStatus((prev) => (prev === "authenticated" ? "anonymous" : prev));
        }
      }),
    []
  );

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await api.login(email, password);
    setToken(access_token);
    // Fetch the identity rather than decoding the JWT client-side: the
    // server is the authority on role and active status, and a dashboard
    // that trusts its own reading of a token is one step from trusting a
    // forged one.
    const me = await api.me();
    setUser(me);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setStatus("anonymous");
  }, []);

  return (
    <AuthContext.Provider
      value={{ status, user, error, login, logout, retry: () => void resolve() }}
    >
      {children}
    </AuthContext.Provider>
  );
}
