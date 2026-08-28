import { describe, expect, test, vi } from "vitest";

import {
  CoreAuthenticationRequiredError,
  CoreUnavailableError,
  createCoreFetch,
} from "./coreFetch";

describe("coreFetch", () => {
  test("clears the in-memory Session on 401", async () => {
    const onUnauthorized = vi.fn();
    const coreFetch = createCoreFetch({
      fetch: vi.fn(async () => new Response(null, { status: 401 })),
      onUnauthorized,
    });

    await expect(coreFetch("/api/data")).rejects.toBeInstanceOf(
      CoreAuthenticationRequiredError,
    );
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  test.each([
    ["503", vi.fn(async () => new Response(null, { status: 503 }))],
    ["network failure", vi.fn(async () => Promise.reject(new TypeError("offline")))],
  ])("preserves Session and exposes retryable unavailability on %s", async (_label, fetch) => {
    const onUnauthorized = vi.fn();
    const coreFetch = createCoreFetch({ fetch, onUnauthorized });

    await expect(coreFetch("/api/data")).rejects.toBeInstanceOf(
      CoreUnavailableError,
    );
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  test("uses same-origin credentials and JSON for body-bearing writes", async () => {
    const fetch = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => Response.json({ status: true }),
    );
    const coreFetch = createCoreFetch({ fetch, onUnauthorized: vi.fn() });

    await coreFetch("/api/researcher/bootstrap", {
      method: "POST",
      body: JSON.stringify({}),
    });

    expect(fetch).toHaveBeenCalledOnce();
    const [, init] = fetch.mock.calls[0];
    expect(init?.credentials).toBe("same-origin");
    expect(new Headers(init?.headers).get("Content-Type")).toBe(
      "application/json",
    );
  });

  test("retains product 404 responses for owner-scoped UI handling", async () => {
    const coreFetch = createCoreFetch({
      fetch: vi.fn(async () => new Response(null, { status: 404 })),
      onUnauthorized: vi.fn(),
    });

    expect((await coreFetch("/api/research-runs/run_missing")).status).toBe(404);
  });
});
