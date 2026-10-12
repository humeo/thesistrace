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

import { authRetryAfter, type AuthErrorCode, type AuthFailure, type AuthResult, } from "./errors";

type AuthContextValue = Readonly<{
  state: AuthState;
  retry: () => Promise<void>;
  sendCode: (email: string, captchaToken: string) => Promise<AuthResult>;
  signIn: (email: string, otp: string) => Promise<AuthResult>;
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
  const generation = useRef(0);
  const sessionRetryAt = useRef(0);
  const cooldowns = useRef<Partial<Record<"signIn" | "signOut" | "sendCode", number>>>({});
  const remaining = useCallback((operation: keyof typeof cooldowns.current): AuthFailure | null => {
    const seconds = Math.ceil(((cooldowns.current[operation] ?? 0) - Date.now()) / 1_000);
    return seconds > 0 ? { ok: false, code: "tooManyRequests", retryAfterSeconds: seconds } : null;
  }, []);
  const limited = useCallback((operation: keyof typeof cooldowns.current, seconds: number | null): AuthFailure => {
    if (seconds === null) return failure("unavailable");
    cooldowns.current[operation] = Date.now() + seconds * 1_000;
    return { ok: false, code: "tooManyRequests", retryAfterSeconds: seconds };
  }, []);
  stateRef.current = state;

  const invalidate = useCallback(() => {
    generation.current += 1;
    sessionRetryAt.current = 0;
    readyResearcherId.current = null;
    refreshInFlight.current = null;
  }, []);

  const clearSession = useCallback(() => {
    invalidate();
    dispatch({ type: "session-missing" });
  }, [invalidate]);

  const bootstrap = useCallback(async (session: PublicSession, epoch: number): Promise<boolean> => {
    const bootstrapFetch = createCoreFetch({
      fetch: (...args) => globalThis.fetch(...args),
      onUnauthorized: () => { if (epoch === generation.current) clearSession(); },
    });
    try {
      const response = await bootstrapFetch("/api/researcher/bootstrap", { method: "POST", body: JSON.stringify({}) });
      if (!response.ok) throw new CoreUnavailableError();
      const payload = await response.json() as unknown;
      if (!isRecord(payload) || payload.researcher_id !== session.researcherId || !isSystemFolderContract(payload.system_folders)) throw new CoreUnavailableError();
      return true;
    } catch {
      return false;
    }
  }, [clearSession]);

  const refreshSession = useCallback(async (forceSetup = false): Promise<void> => {
    if (sessionRetryAt.current > Date.now()) return;
    if (refreshInFlight.current !== null) return refreshInFlight.current;
    let epoch = generation.current;
    const request = (async () => {
      try {
        let retryAfter: number | null = null;
        const result = await authClient.getSession({ fetchOptions: { onError: ({response}) => { retryAfter = authRetryAfter(response); } } });
        if (epoch !== generation.current) return;
        if (result.error !== null) {
          if (result.error.status === 401) clearSession();
          else {
            sessionRetryAt.current = result.error.status === 429 && retryAfter !== null ? Date.now() + retryAfter * 1_000 : 0;
            dispatch({ type: "auth-unavailable", ...(sessionRetryAt.current > 0 ? {retryAt: sessionRetryAt.current} : {}) });
          }
          return;
        }
        const researcherSession = decodePublicSession(result.data);
        if (researcherSession === null) { clearSession(); return; }
        if (stateRef.current.session !== null && stateRef.current.session.researcherId !== researcherSession.researcherId) {
          generation.current += 1;
          epoch = generation.current;
          readyResearcherId.current = null;
          dispatch({type: "session-available", session: researcherSession});
        }
        const setupRequest = forceSetup || readyResearcherId.current !== researcherSession.researcherId
          ? bootstrap(researcherSession, epoch)
          : null;
        const session: PublicSession = { ...researcherSession, operator: await loadOperatorCapability() };
        if (epoch !== generation.current) return;
        if (setupRequest === null) {
          dispatch({ type: "setup-succeeded", session });
          return;
        }
        dispatch({ type: "session-available", session });
        const setupSucceeded = await setupRequest;
        if (epoch !== generation.current) return;
        if (setupSucceeded) {
          readyResearcherId.current = session.researcherId;
          dispatch({ type: "setup-succeeded", session });
        } else {
          dispatch({ type: "setup-failed", session });
        }
      } catch {
        if (epoch === generation.current) dispatch({ type: "auth-unavailable" });
      }
    })();
    refreshInFlight.current = request;
    try { await request; }
    finally { if (refreshInFlight.current === request) refreshInFlight.current = null; }
  }, [bootstrap, clearSession]);

  useEffect(() => setCoreUnauthorizedHandler(clearSession), [clearSession]);

  useEffect(() => {
    void refreshSession();
    const refreshWhenUsable = () => {
      if (document.visibilityState === "visible" && navigator.onLine) void refreshSession();
    };
    const interval = window.setInterval(refreshWhenUsable, SESSION_REFRESH_INTERVAL_MS);
    window.addEventListener("focus", refreshWhenUsable);
    window.addEventListener("online", refreshWhenUsable);
    document.addEventListener("visibilitychange", refreshWhenUsable);
    return () => {
      invalidate();
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshWhenUsable);
      window.removeEventListener("online", refreshWhenUsable);
      document.removeEventListener("visibilitychange", refreshWhenUsable);
    };
  }, [refreshSession, invalidate]);

  const signIn = useCallback(async (email: string, otp: string): Promise<AuthResult> => {
    const cooling = remaining("signIn");
    if (cooling) return cooling;
    invalidate();
    const epoch = generation.current;
    try {
      let retryAfter: number | null = null;
      const result = await authClient.signIn.emailOtp({ email: email.trim().toLowerCase(), otp }, { onError: ({response}) => { retryAfter = authRetryAfter(response); } });
      if (epoch !== generation.current) return failure("operationFailed");
      if (result.error !== null) {
        if (result.error.code === "ACCOUNT_INACTIVE") return failure("accountInactive");
        if (result.error.status === 429) return limited("signIn", retryAfter);
        if (result.error.code === "TOO_MANY_ATTEMPTS") return failure("tooManyAttempts");
        if (result.error.status >= 500) return failure("unavailable");
        if (result.error.code === "INVALID_OTP" || result.error.code === "OTP_EXPIRED") return failure("invalidCode");
        return failure("operationFailed");
      }
      if (isOAuthRedirect(result.data)) {
        // Better Auth owns the OAuth redirect; do not race it with workspace bootstrap.
        return { ok: true };
      }
      readyResearcherId.current = null;
      await refreshSession(true);
      return { ok: true };
    } catch {
      return failure("unavailable");
    }
  }, [refreshSession, invalidate, remaining, limited]);

  const sendCode = useCallback(async (email: string, captchaToken: string): Promise<AuthResult> => {
    const cooling = remaining("sendCode");
    if (cooling) return cooling;
    try {
      const result = await authJson("/api/auth/email-otp/send-verification-otp", {email: email.trim().toLowerCase(), type: "sign-in", captcha_token: captchaToken});
      if (result.status === 429) return limited("sendCode", result.retryAfterSeconds);
      if (!result.ok) return failure(result.status === 403 ? "challengeFailed" : result.status === 503 ? "unavailable" : "codeDeliveryFailed");
      return {ok: true};
    } catch { return failure("codeDeliveryFailed"); }
  }, [remaining, limited]);

  const signOut = useCallback(async (): Promise<AuthResult> => {
    const cooling = remaining("signOut");
    if (cooling) return cooling;
    invalidate();
    const epoch = generation.current;
    try {
      let retryAfter: number | null = null;
      const result = await authClient.signOut({ fetchOptions: { onError: ({response}) => { retryAfter = authRetryAfter(response); } } });
      if (epoch !== generation.current) return failure("operationFailed");
      if (result.error?.status === 429) return limited("signOut", retryAfter);
      if (result.error !== null) return failure("signOutFailed");
      clearSession();
      return { ok: true };
    } catch {
      return failure("signOutFailed");
    }
  }, [clearSession, invalidate, remaining, limited]);

  const value = useMemo<AuthContextValue>(() => ({
    state,
    retry: () => refreshSession(stateRef.current.session !== null
      && readyResearcherId.current !== stateRef.current.session.researcherId),
    sendCode,
    signIn,
    signOut,
  }), [
    refreshSession,
    sendCode,
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
  status: number;
  data: unknown;
  retryAfterSeconds: number | null;
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
  return { data, ok: response.ok, status: response.status, retryAfterSeconds: response.status === 429 ? authRetryAfter(response) : null };
}

function failure(code: AuthErrorCode): Readonly<{ ok: false; code: AuthErrorCode }> {
  return { ok: false, code };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSystemFolderContract(value: unknown): boolean {
  return isRecord(value)
    && value.default === "folder_default"
    && value.batch_research === "folder_batch_research";
}

function isOAuthRedirect(value: unknown): boolean {
  return isRecord(value) && value.redirect === true && typeof value.url === "string";
}
