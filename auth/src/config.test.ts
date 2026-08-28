import { describe, expect, it } from "vitest";

import { readAuthInitializerSettings, readAuthSettings } from "./config.js";

const baseEnvironment = {
  BETTER_AUTH_SECRET: "0123456789abcdef0123456789abcdef",
  RESEND_API_KEY: "test-resend-key",
  RESEND_FROM_EMAIL: "ThesisTrace <noreply@thesistrace.test>",
  THESISTRACE_AUTH_DATABASE_URL:
    "postgresql://auth_runtime:auth-password@postgres:5432/thesistrace",
  THESISTRACE_ENVIRONMENT: "test",
  THESISTRACE_PUBLIC_ORIGIN: "http://127.0.0.1:5173",
  THESISTRACE_RESEND_API_URL: "http://127.0.0.1:8300",
};

const productionEnvironment = {
  ...baseEnvironment,
  BETTER_AUTH_SECRET:
    "a4f781c2d6e9035b8a1f74c092e5bd3680c4f719a2e65b03d8f14c7a9e256bd0",
  THESISTRACE_ENVIRONMENT: "production",
  THESISTRACE_PUBLIC_ORIGIN: "https://thesistrace.test",
  THESISTRACE_RESEND_API_URL: "https://api.resend.com",
};

describe("readAuthSettings", () => {
  it("accepts one exact loopback origin for Test", () => {
    expect(readAuthSettings(baseEnvironment)).toMatchObject({
      environment: "test",
      publicOrigin: "http://127.0.0.1:5173",
      resendApiKey: "test-resend-key",
      resendApiUrl: "http://127.0.0.1:8300",
      resendFromEmail: "ThesisTrace <noreply@thesistrace.test>",
      secureCookies: false,
    });
  });

  it("accepts only the canonical internal Resend fake origin for Compose Test", () => {
    expect(
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_RESEND_API_URL: "http://resend-fake:8300",
      }).resendApiUrl,
    ).toBe("http://resend-fake:8300");
  });

  it.each(["RESEND_API_KEY", "RESEND_FROM_EMAIL", "THESISTRACE_RESEND_API_URL"])(
    "requires the %s Resend setting",
    (name) => {
      expect(() => readAuthSettings({ ...baseEnvironment, [name]: "" })).toThrow(name);
    },
  );

  it.each([
    "https://api.resend.com/",
    "https://resend.example.test",
    "http://127.0.0.1:8300",
  ])("rejects a non-canonical Production Resend URL: %s", (resendApiUrl) => {
    expect(() =>
      readAuthSettings({
        ...productionEnvironment,
        THESISTRACE_RESEND_API_URL: resendApiUrl,
      }),
    ).toThrow(/THESISTRACE_RESEND_API_URL/);
  });

  it.each([
    "https://api.resend.com",
    "http://example.test",
    "http://0.0.0.0:8300",
  ])("rejects a non-loopback Test Resend URL: %s", (resendApiUrl) => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_RESEND_API_URL: resendApiUrl,
      }),
    ).toThrow(/THESISTRACE_RESEND_API_URL/);
  });

  it.each([
    "not-an-email",
    "ThesisTrace <not-an-email>",
    "ThesisTrace <noreply@thesistrace.test>\r\nBcc: attacker@example.test",
  ])("rejects an invalid Resend From value", (fromEmail) => {
    expect(() =>
      readAuthSettings({ ...baseEnvironment, RESEND_FROM_EMAIL: fromEmail }),
    ).toThrow(/RESEND_FROM_EMAIL/);
  });

  it.each([
    "http://127.0.0.1:5173/",
    "http://127.0.0.1:5173/path",
    "http://user@example.test",
    "ftp://example.test",
  ])("rejects a non-canonical public origin: %s", (publicOrigin) => {
    expect(() =>
      readAuthSettings({ ...baseEnvironment, THESISTRACE_PUBLIC_ORIGIN: publicOrigin }),
    ).toThrow(/THESISTRACE_PUBLIC_ORIGIN/);
  });

  it.each([
    "http://example.test",
    "https://localhost",
    "https://localhost.",
    "https://admin.localhost",
    "https://admin.localhost.",
    "https://127.0.0.1",
    "https://127.0.0.2",
    "https://0.0.0.0",
    "https://[::1]",
    "https://[::ffff:7f00:1]",
  ])(
    "rejects an insecure or loopback Production origin: %s",
    (publicOrigin) => {
      expect(() =>
        readAuthSettings({
          ...productionEnvironment,
          THESISTRACE_PUBLIC_ORIGIN: publicOrigin,
        }),
      ).toThrow(/THESISTRACE_PUBLIC_ORIGIN/);
    },
  );

  it("accepts one canonical 32-byte hexadecimal Production secret", () => {
    expect(readAuthSettings(productionEnvironment).secret).toBe(
      productionEnvironment.BETTER_AUTH_SECRET,
    );
  });

  it.each([
    "",
    "change-me",
    "01234567890123456789012345678901",
    "0123456789abcdef".repeat(4),
    "00".repeat(32),
    "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-",
  ])(
    "rejects a missing, non-canonical, or predictable Production secret",
    (secret) => {
      expect(() =>
        readAuthSettings({
          ...productionEnvironment,
          BETTER_AUTH_SECRET: secret,
        }),
      ).toThrow(/BETTER_AUTH_SECRET/);
    },
  );

  it.each([
    "BETTER_AUTH_SECRETS",
    "BETTER_AUTH_TELEMETRY",
    "BETTER_AUTH_TELEMETRY_DEBUG",
    "BETTER_AUTH_TELEMETRY_ENDPOINT",
    "BETTER_AUTH_TELEMETRY_ID",
    "BETTER_AUTH_TRUSTED_ORIGINS",
  ])("rejects Better Auth's ambient override: %s", (name) => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        [name]: "enabled-by-ambient-environment",
      }),
    ).toThrow(name);
  });

  it("rejects a non-PostgreSQL Auth database URL", () => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_AUTH_DATABASE_URL: "https://database.test",
      }),
    ).toThrow(/THESISTRACE_AUTH_DATABASE_URL/);
  });

  it("requires the isolated Auth runtime database role", () => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_AUTH_DATABASE_URL:
          "postgresql://thesistrace_owner:owner-password@postgres:5432/thesistrace",
      }),
    ).toThrow(/auth_runtime/);
  });

  it.each([
    "postgresql://auth%ZZ_runtime:auth-password@postgres:5432/thesistrace",
    "postgresql://auth_runtime:auth%ZZpassword@postgres:5432/thesistrace",
    "postgresql://auth_runtime:auth-password@postgres:5432/thesis%ZZtrace",
  ])("rejects malformed database URL percent-encoding: %s", (databaseUrl) => {
    expect(() =>
      readAuthSettings({
        ...baseEnvironment,
        THESISTRACE_AUTH_DATABASE_URL: databaseUrl,
      }),
    ).toThrow(/THESISTRACE_AUTH_DATABASE_URL/);
  });
});

describe("readAuthInitializerSettings", () => {
  it("accepts only the owner database role", () => {
    expect(
      readAuthInitializerSettings({
        THESISTRACE_OWNER_DATABASE_URL:
          "postgresql://thesistrace_owner:owner-password@postgres:5432/thesistrace",
      }),
    ).toEqual({
      databaseUrl:
        "postgresql://thesistrace_owner:owner-password@postgres:5432/thesistrace",
    });

    expect(() =>
      readAuthInitializerSettings({
        THESISTRACE_OWNER_DATABASE_URL:
          "postgresql://auth_runtime:auth-password@postgres:5432/thesistrace",
      }),
    ).toThrow(/thesistrace_owner/);
  });
});
