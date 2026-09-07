import { describe, expect, it } from "vitest";

import {
  createOpaqueToken,
  parseOpaqueToken,
  secretFingerprint,
  tokenHashMatches,
  unknownEmailHmac,
} from "./security.js";

describe("Auth opaque security values", () => {
  it("builds one UUID-addressed token from exactly 32 random bytes", () => {
    const token = createOpaqueToken(
      "00000000-0000-4000-8000-000000000001",
      () => Buffer.alloc(32, 0xab),
    );
    const parsed = parseOpaqueToken(token);

    expect(token).toBe(
      "00000000-0000-4000-8000-000000000001." + "q6urq6urq6urq6urq6urq6urq6urq6urq6urq6urq6s",
    );
    expect(parsed?.id).toBe("00000000-0000-4000-8000-000000000001");
    expect(parsed?.hash).toHaveLength(32);
    expect(token).not.toContain("researcher@example.com");
  });

  it.each([
    "",
    "not-a-token",
    "00000000-0000-4000-8000-000000000001.short",
    `00000000-0000-4000-8000-000000000001.${"a".repeat(42)}!`,
    `00000000-0000-0000-0000-000000000000.${"a".repeat(43)}`,
  ])("rejects a malformed opaque token", (token) => {
    expect(parseOpaqueToken(token)).toBeNull();
  });

  it("compares the committed token hash without length-dependent exceptions", () => {
    const token = createOpaqueToken(
      "00000000-0000-4000-8000-000000000001",
      () => Buffer.alloc(32, 0x11),
    );
    const parsed = parseOpaqueToken(token);
    expect(parsed).not.toBeNull();

    expect(tokenHashMatches(parsed?.hash ?? Buffer.alloc(0), parsed?.hash)).toBe(true);
    expect(tokenHashMatches(Buffer.alloc(31), parsed?.hash)).toBe(false);
    expect(tokenHashMatches(Buffer.alloc(32, 0x22), parsed?.hash)).toBe(false);
  });

  it("uses keyed HMAC for unknown emails and SHA-256 for secret rotation", () => {
    const first = unknownEmailHmac("auth-secret", "unknown@example.com");
    const second = unknownEmailHmac("auth-secret", "unknown@example.com");

    expect(first).toEqual(second);
    expect(first).toHaveLength(32);
    expect(first).not.toEqual(
      unknownEmailHmac("auth-secret", "different@example.com"),
    );
    expect(secretFingerprint("auth-secret")).toMatch(/^[0-9a-f]{64}$/);
  });
});
