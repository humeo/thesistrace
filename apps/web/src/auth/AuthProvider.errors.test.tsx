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
  vi.stubGlobal("fetch", async () => Response.json({ code }, { status, headers: status === 429 ? {"Retry-After": "37"} : {} }));
  await withAuth(async (auth) => {
    expect(await auth.inspectInvitation("invitation-token")).toEqual({ ok: false, code: expected, ...(status === 429 ? {retryAfterSeconds: 37} : {}) });
    expect(await auth.acceptInvitation("invitation-token", "unused-password")).toEqual({ ok: false, code: expected, ...(status === 429 ? {retryAfterSeconds: 37} : {}) });
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


test("carries server retry time for code delivery and does not retry during cooldown", async () => {
  const request = vi.fn(async () => Response.json({code: "AUTH_RATE_LIMITED"}, {status: 429, headers: {"Retry-After": "37"}}));
  vi.stubGlobal("fetch", request);
  await withAuth(async auth => {
    expect(await auth.sendCode("researcher@example.com", "test-challenge")).toEqual({ok: false, code: "tooManyRequests", retryAfterSeconds: 37});
    expect(await auth.sendCode("different@example.com", "test-challenge")).toMatchObject({ok: false, code: "tooManyRequests"});
  });
  expect(request).toHaveBeenCalledTimes(1);
});

test.each([null, "NaN", "179082411974232", "0", "-1"])("rejects invalid retry metadata %s", async retry => {
  vi.stubGlobal("fetch", async () => Response.json({}, {status: 429, headers: retry === null ? {} : {"Retry-After": retry}}));
  await withAuth(async auth => expect(await auth.sendCode("researcher@example.com", "test-challenge")).toEqual({ok: false, code: "unavailable"}));
});

test("uses the official client response hook for sign-in recovery time", async () => {
  emailOtp.mockImplementation(async (_body, options) => {
    options.onError({response: new Response(null, {status: 429, headers: {"Retry-After": "23"}})});
    return {error: {code: "UNKNOWN_REASON", status: 429}};
  });
  await withAuth(async auth => expect(await auth.signIn("researcher@example.com", "123456")).toEqual({ok: false, code: "tooManyRequests", retryAfterSeconds: 23}));
});

 test("preserves long email-budget retry times", async()=>{
 vi.stubGlobal("fetch", async()=>Response.json({}, {status:429,headers:{"Retry-After":"3600"}}));
 await withAuth(async auth=>expect(await auth.sendCode("researcher@example.com", "test-challenge")).toEqual({ok:false,code:"tooManyRequests",retryAfterSeconds:3600}));
 });
