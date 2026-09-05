import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";

import { authClient } from "./client";
import {
  CoreAuthenticationRequiredError,
  CoreUnavailableError,
  createCoreFetch,
  setCoreUnauthorizedHandler,
} from "./coreFetch";
import { loadOperatorCapability } from "./operatorCapability";
import {
  authStateReducer,
  decodePublicSession,
  SESSION_REFRESH_INTERVAL_MS,
  type AuthState,
  type PublicSession,
} from "./session";

type AuthResult = Readonly<{ ok: true }> | Readonly<{ ok: false; message: string }>;

type AuthContextValue = Readonly<{
  state: AuthState;
  acceptInvitation: (token: string, password: string) => Promise<AuthResult>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<AuthResult>;
  inspectInvitation: (token: string) => Promise<Readonly<{ email: string }> | null>;
  requestPasswordReset: (email: string) => Promise<AuthResult>;
  resetPassword: (token: string, newPassword: string) => Promise<AuthResult>;
  retry: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<AuthResult>;
  signOut: () => Promise<AuthResult>;
}>;

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(authStateReducer, {
    status: "loading",
    session: null,
  });
  const readyResearcherId = useRef<string | null>(null);
  const stateRef = useRef(state);
  const refreshInFlight = useRef<Promise<void> | null>(null);
  stateRef.current = state;

  const bootstrap = useCallback(async (session: PublicSession): Promise<void> => {
    const bootstrapFetch = createCoreFetch({
      fetch: (...args) => globalThis.fetch(...args),
      onUnauthorized: () => dispatch({ type: "core-unauthorized" }),
    });
    try {
      const response = await bootstrapFetch("/api/researcher/bootstrap", {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (!response.ok) throw new CoreUnavailableError();
      const payload = await response.json() as unknown;
      if (
        !isRecord(payload)
        || payload.researcher_id !== session.researcherId
        || !isSystemFolderContract(payload.system_folders)
      ) throw new CoreUnavailableError();
      readyResearcherId.current = session.researcherId;
      dispatch({ type: "setup-succeeded", session });
    } catch (error) {
      if (error instanceof CoreAuthenticationRequiredError) return;
      dispatch({ type: "setup-failed", session });
    }
  }, []);

  const refreshSession = useCallback(async (forceSetup = false): Promise<void> => {
    if (refreshInFlight.current !== null) return refreshInFlight.current;
    const request = (async () => {
      try {
        const result = await authClient.getSession();
        if (result.error !== null) {
          if (result.error.status === 401) {
            readyResearcherId.current = null;
            dispatch({ type: "session-missing" });
          } else {
            dispatch({ type: "auth-unavailable" });
          }
          return;
        }
        const researcherSession = decodePublicSession(result.data);
        if (researcherSession === null) {
          readyResearcherId.current = null;
          dispatch({ type: "session-missing" });
          return;
        }
        const session: PublicSession = {
          ...researcherSession,
          operator: await loadOperatorCapability(),
        };
        if (!forceSetup && readyResearcherId.current === session.researcherId) {
          dispatch({ type: "setup-succeeded", session });
          return;
        }
        dispatch({ type: "session-available", session });
        await bootstrap(session);
      } catch {
        dispatch({ type: "auth-unavailable" });
      }
    })();
    refreshInFlight.current = request;
    try {
      await request;
    } finally {
      refreshInFlight.current = null;
    }
  }, [bootstrap]);

  useEffect(() => setCoreUnauthorizedHandler(() => {
    readyResearcherId.current = null;
    dispatch({ type: "core-unauthorized" });
  }), []);

  useEffect(() => {
    void refreshSession();
    const refreshWhenUsable = () => {
      if (document.visibilityState === "visible" && navigator.onLine) {
        void refreshSession();
      }
    };
    const interval = window.setInterval(refreshWhenUsable, SESSION_REFRESH_INTERVAL_MS);
    window.addEventListener("focus", refreshWhenUsable);
    window.addEventListener("online", refreshWhenUsable);
    document.addEventListener("visibilitychange", refreshWhenUsable);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshWhenUsable);
      window.removeEventListener("online", refreshWhenUsable);
      document.removeEventListener("visibilitychange", refreshWhenUsable);
    };
  }, [refreshSession]);

  const signIn = useCallback(async (email: string, password: string): Promise<AuthResult> => {
    try {
      const result = await authClient.signIn.email({ email, password });
      if (result.error !== null) return failure("Email or password is incorrect.");
      if (result.data?.redirect && result.data.url) {
        // Better Auth owns the OAuth redirect; do not race it with workspace bootstrap.
        return { ok: true };
      }
      readyResearcherId.current = null;
      await refreshSession(true);
      return { ok: true };
    } catch {
      return failure("Authentication is temporarily unavailable.");
    }
  }, [refreshSession]);

  const signOut = useCallback(async (): Promise<AuthResult> => {
    try {
      const result = await authClient.signOut();
      if (result.error !== null) return failure("Logout could not be completed.");
      readyResearcherId.current = null;
      dispatch({ type: "session-missing" });
      return { ok: true };
    } catch {
      return failure("Logout could not be completed.");
    }
  }, []);

  const inspectInvitation = useCallback(async (token: string) => {
    const response = await authJson("/api/auth/researcher-invitation/inspect", { token });
    if (!response.ok || !isRecord(response.data) || typeof response.data.email !== "string") {
      return null;
    }
    return { email: response.data.email };
  }, []);

  const acceptInvitation = useCallback(async (
    token: string,
    password: string,
  ): Promise<AuthResult> => {
    try {
      const response = await authJson("/api/auth/researcher-invitation/accept", {
        password,
        token,
      });
      if (!response.ok) return failure("This invitation is invalid or has expired.");
      readyResearcherId.current = null;
      await refreshSession(true);
      return { ok: true };
    } catch {
      return failure("Authentication is temporarily unavailable.");
    }
  }, [refreshSession]);

  const requestPasswordReset = useCallback(async (email: string): Promise<AuthResult> => {
    try {
      const result = await authClient.requestPasswordReset({ email });
      if (result.error !== null) return failure("The reset request could not be sent.");
      return { ok: true };
    } catch {
      return failure("The reset request could not be sent.");
    }
  }, []);

  const resetPassword = useCallback(async (
    token: string,
    newPassword: string,
  ): Promise<AuthResult> => {
    try {
      const response = await authJson("/api/auth/reset-password", { newPassword, token });
      if (!response.ok) return failure("This reset link is invalid or has expired.");
      readyResearcherId.current = null;
      dispatch({ type: "session-missing" });
      return { ok: true };
    } catch {
      return failure("The password could not be reset.");
    }
  }, []);

  const changePassword = useCallback(async (
    currentPassword: string,
    newPassword: string,
  ): Promise<AuthResult> => {
    try {
      const result = await authClient.changePassword({ currentPassword, newPassword });
      if (result.error !== null) return failure("The current password is incorrect.");
      return { ok: true };
    } catch {
      return failure("The password could not be changed.");
    }
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    state,
    acceptInvitation,
    changePassword,
    inspectInvitation,
    requestPasswordReset,
    resetPassword,
    retry: () => refreshSession(stateRef.current.session !== null
      && readyResearcherId.current !== stateRef.current.session.researcherId),
    signIn,
    signOut,
  }), [
    acceptInvitation,
    changePassword,
    inspectInvitation,
    requestPasswordReset,
    resetPassword,
    refreshSession,
    signIn,
    signOut,
    state,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) throw new Error("useAuth requires AuthProvider");
  return value;
}

async function authJson(path: string, body: Record<string, string>): Promise<Readonly<{
  ok: boolean;
  data: unknown;
}>> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // Status is authoritative; do not retain response text that may contain secrets.
  }
  return { data, ok: response.ok };
}

function failure(message: string): AuthResult {
  return { ok: false, message };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSystemFolderContract(value: unknown): boolean {
  return isRecord(value)
    && value.default === "folder_default"
    && value.batch_research === "folder_batch_research";
}
