import { describe, expect, it } from "vitest";

import {
  createAuthHttpObserver,
  type AuthHttpEvent,
  normalizeAuthRoute,
} from "./http-observability.js";

describe("Auth HTTP observability", () => {
  it("keeps only the gateway request ID and a normalized fixed route", () => {
    const events: AuthHttpEvent[] = [];
    const ticks = [10, 14][Symbol.iterator]();
    const observer = createAuthHttpObserver({
      clock: () => new Date("2026-08-29T00:00:00.000Z"),
      monotonicMilliseconds: () => ticks.next().value ?? 14,
      requestIdFactory: () => "00000000-0000-4000-8000-000000000099",
      write: (event) => events.push(event),
    });
    const observation = observer.start(
      new Headers({
        cookie: "cookie-canary=private",
        "x-request-id": "00000000-0000-4000-8000-000000000001",
      }),
    );

    observer.complete(observation, {
      method: "POST",
      path: "/api/auth/sign-in/email",
      status: 401,
    });

    expect(events).toEqual([
      {
        component: "auth_http",
        duration_ms: 4,
        event: "http_request_completed",
        http_request_id: "00000000-0000-4000-8000-000000000001",
        level: "INFO",
        method: "POST",
        route: "/api/auth/sign-in/email",
        status_code: 401,
        timestamp: "2026-08-29T00:00:00.000Z",
      },
    ]);
    expect(JSON.stringify(events)).not.toContain("cookie-canary");
  });

  it("replaces forged IDs and collapses unknown token-bearing paths", () => {
    const events: AuthHttpEvent[] = [];
    const ticks = [20, 20][Symbol.iterator]();
    const observer = createAuthHttpObserver({
      monotonicMilliseconds: () => ticks.next().value ?? 20,
      requestIdFactory: () => "00000000-0000-4000-8000-000000000002",
      write: (event) => events.push(event),
    });
    const observation = observer.start(
      new Headers({ "x-request-id": "token-canary-forged-request-id" }),
    );
    observer.complete(observation, {
      method: "GET",
      path: "/api/auth/reset-password/token-canary-path",
      status: 404,
    });

    expect(observation.requestId).toBe(
      "00000000-0000-4000-8000-000000000002",
    );
    expect(events[0]?.route).toBe("/api/auth/*");
    expect(JSON.stringify(events)).not.toContain("token-canary");
  });

  it("never records an unmatched raw path", () => {
    expect(normalizeAuthRoute("/private/formula-canary")).toBe("/unmatched");
    expect(normalizeAuthRoute("/internal/token-canary")).toBe("/internal/*");
  });
});
