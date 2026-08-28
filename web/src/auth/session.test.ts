import { describe, expect, test } from "vitest";

import {
  authStateReducer,
  authenticatedResearcherId,
  decodePublicSession,
  SESSION_REFRESH_INTERVAL_MS,
  type AuthState,
} from "./session";

const session = {
  researcherId: "00000000-0000-4000-8000-000000000001",
  email: "researcher@example.test",
  displayLabel: "researcher",
};

describe("public Session state", () => {
  test("retains only display identity and never the Session token", () => {
    const decoded = decodePublicSession({
      session: { token: "must-not-enter-browser-state", expiresAt: "tomorrow" },
      user: {
        id: session.researcherId,
        email: session.email,
        name: session.displayLabel,
        active: true,
      },
    });

    expect(decoded).toEqual(session);
    expect(JSON.stringify(decoded)).not.toContain("must-not-enter-browser-state");
  });

  test("treats null and inactive Sessions as anonymous", () => {
    expect(decodePublicSession(null)).toBeNull();
    expect(
      decodePublicSession({
        session: {},
        user: { ...session, id: session.researcherId, active: false },
      }),
    ).toBeNull();
  });

  test("rejects malformed authenticated responses", () => {
    expect(() => decodePublicSession({ session: {}, user: { active: true } })).toThrow(
      "Auth Session response is invalid",
    );
  });

  test("moves a new Session through setup before product access", () => {
    let state: AuthState = { status: "loading", session: null };
    state = authStateReducer(state, { type: "session-available", session });
    expect(state).toEqual({ status: "setup", session });
    state = authStateReducer(state, { type: "setup-succeeded", session });
    expect(state).toEqual({ status: "authenticated", session });
  });

  test("preserves identity during Core and Auth outages but clears it on 401", () => {
    const authenticated: AuthState = { status: "authenticated", session };
    expect(
      authStateReducer(authenticated, { type: "setup-failed", session }),
    ).toEqual({ status: "setup-failure", session });
    expect(
      authStateReducer(authenticated, { type: "auth-unavailable" }),
    ).toEqual({ status: "unavailable", session });
    expect(
      authStateReducer(authenticated, { type: "core-unauthorized" }),
    ).toEqual({ status: "anonymous", session: null });
  });

  test("uses the agreed visible online refresh interval", () => {
    expect(SESSION_REFRESH_INTERVAL_MS).toBe(12 * 60 * 60 * 1000);
  });

  test("removes the product subtree, and therefore its polling effects, after Core 401", () => {
    const authenticated: AuthState = { status: "authenticated", session };
    expect(authenticatedResearcherId(authenticated)).toBe(session.researcherId);

    const anonymous = authStateReducer(authenticated, { type: "core-unauthorized" });
    expect(authenticatedResearcherId(anonymous)).toBeNull();
  });
});
