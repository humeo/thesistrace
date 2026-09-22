// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";

const { emailOtp } = vi.hoisted(() => ({ emailOtp: vi.fn() }));
vi.mock("./client", () => ({ authClient: {
  getSession: async () => ({ data: null, error: null }),
  signIn: { emailOtp },
} }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.unstubAllGlobals());

async function withAuth(assertion: (auth: ReturnType<typeof useAuth>) => Promise<void>) {
  let auth!: ReturnType<typeof useAuth>;
  function Consumer() { auth = useAuth(); return null; }
  const container = document.createElement("div");
  const root = createRoot(container);
  try {
    await act(async () => root.render(<AuthProvider><Consumer /></AuthProvider>));
    await act(async () => assertion(auth));
  } finally { await act(async () => root.unmount()); }
}

test.each([
  ["INVITATION_INVALID", 400, "invitationExpired"],
  ["AUTH_RATE_LIMITED", 429, "tooManyRequests"],
  ["AUTH_SERVICE_UNAVAILABLE", 503, "unavailable"],
  ["ORIGIN_NOT_ALLOWED", 403, "operationFailed"],
  ["UNKNOWN_REASON", 400, "operationFailed"],
] as const)("invitation failures preserve the %s reason", async (code, status, expected) => {
  vi.stubGlobal("fetch", async () => Response.json({ code }, { status }));
  await withAuth(async (auth) => {
    expect(await auth.inspectInvitation("invitation-token")).toEqual({ ok: false, code: expected });
    expect(await auth.acceptInvitation("invitation-token", "unused-password")).toEqual({ ok: false, code: expected });
  });
});

test("malformed invitation inspection is an operation failure, not an expired invitation", async () => {
  vi.stubGlobal("fetch", async () => Response.json({}));
  await withAuth(async (auth) => {
    expect(await auth.inspectInvitation("invitation-token")).toEqual({ ok: false, code: "operationFailed" });
  });
});

test.each([
  ["INVALID_OTP", 400, "invalidCode"],
  ["OTP_EXPIRED", 400, "invalidCode"],
  ["TOO_MANY_ATTEMPTS", 403, "tooManyAttempts"],
  ["ACCOUNT_INACTIVE", 403, "accountInactive"],
  ["UNKNOWN_REASON", 400, "operationFailed"],
  ["UNKNOWN_REASON", 503, "unavailable"],
] as const)("email verification preserves the %s reason", async (code, status, expected) => {
  emailOtp.mockResolvedValue({ error: { code, status } });
  await withAuth(async (auth) => {
    expect(await auth.signIn("researcher@example.com", "123456")).toEqual({ ok: false, code: expected });
  });
});
