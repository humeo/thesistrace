import { describe, expect, it, vi } from "vitest";

import { AgentAuthenticationUnavailableError } from "./failure.js";
import { createSessionVerifier } from "./session-verifier.js";

const activeResearcher = {
  active: true,
  display_label: "Researcher",
  email: "researcher@example.test",
  researcher_id: "00000000-0000-4000-8000-000000000001",
};

describe("Agent Session verifier", () => {
  it("forwards only the Login Session Cookie to the private Auth adapter", async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      Response.json(activeResearcher));
    const verify = createSessionVerifier({
      authInternalOrigin: "http://auth:8200",
      fetch,
    });

    await expect(
      verify(new Headers({
        authorization: "Bearer browser-canary",
        cookie: "analytics=discard-me; thesistrace.session_token=session-canary",
        origin: "https://attacker.example",
        "x-request-id": "request-canary",
      })),
    ).resolves.toEqual(activeResearcher);
    expect(fetch).toHaveBeenCalledOnce();
    const [input, init] = fetch.mock.calls[0] ?? [];
    expect(input).toBe("http://auth:8200/internal/session/verify");
    expect(init?.method).toBe("POST");
    expect(init?.redirect).toBe("error");
    expect(Object.fromEntries(new Headers(init?.headers).entries())).toEqual({
      cookie: "thesistrace.session_token=session-canary",
    });
  });

  it("maps an invalid, expired, revoked, or inactive Session to missing", async () => {
    const verify = createSessionVerifier({
      authInternalOrigin: "http://auth:8200",
      fetch: vi.fn(async () => Response.json(
        { code: "AUTHENTICATION_REQUIRED" },
        { status: 401 },
      )),
    });

    await expect(verify(new Headers())).resolves.toBeNull();
  });

  it("keeps enough bounded time for a loaded private Auth verification", async () => {
    vi.useFakeTimers();
    const timeout = vi.spyOn(AbortSignal, "timeout").mockImplementation((milliseconds) => {
      const controller = new AbortController();
      setTimeout(
        () => controller.abort(new DOMException("Timed out", "TimeoutError")),
        milliseconds,
      );
      return controller.signal;
    });
    try {
      const fetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((resolve, reject) => {
          const responseTimer = setTimeout(
            () => resolve(Response.json(activeResearcher)),
            3_000,
          );
          init?.signal?.addEventListener("abort", () => {
            clearTimeout(responseTimer);
            reject(init.signal?.reason);
          }, { once: true });
        }));
      const verify = createSessionVerifier({
        authInternalOrigin: "http://auth:8200",
        fetch,
      });
      const verified = verify(new Headers()).then(
        (value) => ({ value }),
        (error: unknown) => ({ error }),
      );

      await vi.advanceTimersByTimeAsync(3_000);

      const outcome = await verified;
      if ("error" in outcome) throw outcome.error;
      expect(outcome.value).toEqual(activeResearcher);
      expect(timeout).toHaveBeenCalledWith(5_000);
    } finally {
      timeout.mockRestore();
      vi.useRealTimers();
    }
  });

  it.each([
    ["Auth unavailable", vi.fn(async () => Response.json({}, { status: 503 }))],
    ["Auth timeout", vi.fn(async () => { throw new DOMException("Timed out", "TimeoutError"); })],
    ["malformed success", vi.fn(async () => Response.json({ active: true }))],
  ])("fails closed for %s", async (_name, fetch) => {
    const verify = createSessionVerifier({
      authInternalOrigin: "http://auth:8200",
      fetch,
    });

    await expect(verify(new Headers())).rejects.toBeInstanceOf(
      AgentAuthenticationUnavailableError,
    );
  });
});
