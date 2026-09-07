import { isUuid } from "../uuid";

export const SESSION_REFRESH_INTERVAL_MS = 12 * 60 * 60 * 1000;

export type PublicSession = Readonly<{
  researcherId: string;
  email: string;
  displayLabel: string;
  operator: boolean;
}>;

export type AuthState =
  | Readonly<{ status: "loading"; session: null }>
  | Readonly<{ status: "anonymous"; session: null }>
  | Readonly<{ status: "setup"; session: PublicSession }>
  | Readonly<{ status: "setup-failure"; session: PublicSession }>
  | Readonly<{ status: "authenticated"; session: PublicSession }>
  | Readonly<{ status: "unavailable"; session: PublicSession | null }>;

export type AuthAction =
  | Readonly<{ type: "session-available"; session: PublicSession }>
  | Readonly<{ type: "session-missing" }>
  | Readonly<{ type: "setup-succeeded"; session: PublicSession }>
  | Readonly<{ type: "setup-failed"; session: PublicSession }>
  | Readonly<{ type: "auth-unavailable" }>
  | Readonly<{ type: "core-unauthorized" }>;

export function authStateReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case "session-available":
      if (
        state.session?.researcherId === action.session.researcherId
        && state.status === "authenticated"
      ) return { status: "authenticated", session: action.session };
      return { status: "setup", session: action.session };
    case "session-missing":
    case "core-unauthorized":
      return { status: "anonymous", session: null };
    case "setup-succeeded":
      return { status: "authenticated", session: action.session };
    case "setup-failed":
      return { status: "setup-failure", session: action.session };
    case "auth-unavailable":
      return { status: "unavailable", session: state.session };
  }
}

export function authenticatedResearcherId(state: AuthState): string | null {
  return state.status === "authenticated" ? state.session.researcherId : null;
}

export function decodePublicSession(value: unknown): PublicSession | null {
  if (value === null) return null;
  if (!isRecord(value) || !isRecord(value.user)) {
    throw new Error("Auth Session response is invalid");
  }
  const user = value.user;
  if (user.active === false) return null;
  if (
    user.active !== true
    || typeof user.id !== "string"
    || !isUuid(user.id)
    || typeof user.email !== "string"
    || !isEmail(user.email)
    || typeof user.name !== "string"
    || user.name.trim() === ""
  ) {
    throw new Error("Auth Session response is invalid");
  }
  return {
    researcherId: user.id,
    email: user.email,
    displayLabel: user.name,
    operator: false,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}
