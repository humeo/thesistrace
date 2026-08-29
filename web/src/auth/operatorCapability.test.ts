import { describe, expect, it, vi } from "vitest";

import {
  loadOperatorCapability,
  OperatorCapabilityUnavailableError,
} from "./operatorCapability";

describe("Operator capability boundary", () => {
  it("accepts only the exact server-derived Operator grant", async () => {
    const request = vi.fn(async () => Response.json({ operator: true }));

    await expect(loadOperatorCapability(request)).resolves.toBe(true);
    expect(request).toHaveBeenCalledWith(
      "/api/auth/operator/capability",
      { credentials: "same-origin" },
    );
  });

  it("treats the indistinguishable 404 as an ordinary Researcher", async () => {
    await expect(loadOperatorCapability(
      vi.fn(async () => new Response(null, { status: 404 })),
    )).resolves.toBe(false);
  });

  it.each([
    () => Response.json({ operator: false }),
    () => Response.json({ operator: true, role: "admin" }),
    () => Response.json({ code: "AUTH_SERVICE_UNAVAILABLE" }, { status: 503 }),
  ])("fails closed on a malformed or unavailable capability response", async (reply) => {
    await expect(loadOperatorCapability(vi.fn(async () => reply()))).rejects
      .toBeInstanceOf(OperatorCapabilityUnavailableError);
  });
});
