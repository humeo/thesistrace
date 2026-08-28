import { describe, expect, it } from "vitest";

import { canonicalizeEmail } from "./identity.js";

const emailAtLimit = `a@${"b".repeat(63)}.${"c".repeat(63)}.${"d".repeat(63)}.${"e".repeat(60)}`;

describe("canonicalizeEmail", () => {
  it("trims and lowercases email", () => {
    expect(canonicalizeEmail("  Researcher@Example.COM  ")).toBe(
      "researcher@example.com",
    );
  });

  it("accepts 254 characters and rejects 255", () => {
    expect(emailAtLimit).toHaveLength(254);
    expect(canonicalizeEmail(emailAtLimit)).toBe(emailAtLimit);
    expect(() => canonicalizeEmail(`${emailAtLimit}e`)).toThrow(/EMAIL_INVALID/);
  });

  it.each(["", "not-an-email", "researcher @example.com"])(
    "rejects an invalid email without reflecting it: %s",
    (email) => {
      expect(() => canonicalizeEmail(email)).toThrowError("EMAIL_INVALID");
    },
  );
});
