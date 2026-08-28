import { Pool } from "pg";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createThesisTraceAuth } from "./auth.js";
import type { AuthSettings } from "./config.js";

const settings: AuthSettings = {
  databaseUrl: "postgresql://auth_runtime:password@127.0.0.1:5432/thesistrace",
  environment: "test",
  host: "127.0.0.1",
  port: 8200,
  publicOrigin: "http://127.0.0.1:5173",
  secret: "0123456789abcdef0123456789abcdef",
  secureCookies: false,
};

describe("ThesisTrace Better Auth configuration", () => {
  const ambientOverrideNames = [
    "BETTER_AUTH_SECRETS",
    "BETTER_AUTH_TELEMETRY",
    "BETTER_AUTH_TELEMETRY_DEBUG",
    "BETTER_AUTH_TELEMETRY_ENDPOINT",
    "BETTER_AUTH_TELEMETRY_ID",
    "BETTER_AUTH_TRUSTED_ORIGINS",
  ] as const;
  const originalOverrides = new Map(
    ambientOverrideNames.map((name) => [name, process.env[name]]),
  );

  beforeEach(() => {
    for (const name of ambientOverrideNames) {
      delete process.env[name];
    }
  });

  afterEach(() => {
    for (const name of ambientOverrideNames) {
      const original = originalOverrides.get(name);
      if (original === undefined) {
        delete process.env[name];
      } else {
        process.env[name] = original;
      }
    }
  });

  it("uses only database-backed email/password and revocable Sessions", async () => {
    const pool = new Pool({ connectionString: settings.databaseUrl });
    try {
      const auth = createThesisTraceAuth(settings, pool);

      expect(auth.options.baseURL).toBe(settings.publicOrigin);
      expect(auth.options.basePath).toBe("/api/auth");
      expect(auth.options.trustedOrigins).toEqual([settings.publicOrigin]);
      expect("plugins" in auth.options).toBe(false);
      expect(auth.options.emailAndPassword).toMatchObject({
        enabled: true,
        maxPasswordLength: 128,
        minPasswordLength: 12,
      });
      expect(auth.options.session).toEqual({
        cookieCache: { enabled: false },
        expiresIn: 60 * 60 * 24 * 7,
        updateAge: 60 * 60 * 24,
      });
      expect(auth.options.disabledPaths).toEqual(
        expect.arrayContaining([
          "/list-accounts",
          "/list-sessions",
          "/sign-in/social",
          "/update-session",
          "/update-user",
        ]),
      );
      expect(auth.options.rateLimit).toMatchObject({
        enabled: true,
        storage: "database",
      });
      expect(auth.options.advanced).toMatchObject({
        cookiePrefix: "thesistrace",
        database: { generateId: "uuid" },
        disableCSRFCheck: false,
        disableOriginCheck: false,
        useSecureCookies: false,
      });
      expect(auth.options.user?.additionalFields).toEqual({
        active: {
          defaultValue: true,
          input: false,
          required: true,
          type: "boolean",
        },
      });
    } finally {
      await pool.end();
    }
  });

  it.each(ambientOverrideNames)(
    "refuses Better Auth's ambient override at construction: %s",
    async (name) => {
      process.env[name] = "enabled-by-ambient-environment";
      const pool = new Pool({ connectionString: settings.databaseUrl });
      try {
        expect(() => createThesisTraceAuth(settings, pool)).toThrow(name);
      } finally {
        await pool.end();
      }
    },
  );
});
