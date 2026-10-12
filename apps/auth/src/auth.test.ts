import { Pool } from "pg";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createThesisTraceAuth,
  type AuthLifecycleDependencies,
} from "./auth.js";
import { authTestSettings } from "../test-fixtures/auth-settings.js";

// Configuration unit tests do not start the provider's database resource seeding.
// The real plugin is exercised against PostgreSQL in mcp-connections.integration.test.
vi.mock("@better-auth/oauth-provider", () => ({
  oauthProvider: (options: unknown) => ({ id: "oauth-provider", options }),
}));

const settings = authTestSettings();

function lifecycle(
  overrides: Partial<AuthLifecycleDependencies> = {},
): AuthLifecycleDependencies {
  return {
    backgroundTask: vi.fn(),
    isResearcherActive: vi.fn(async () => true),
    recordSession: vi.fn(),
    ...overrides,
  };
}

describe("ThesisTrace Better Auth configuration", () => {
  it("creates a verified canonical identity only through email OTP", async () => {
    const pool = new Pool({connectionString: settings.databaseUrl});
    try {
      const auth = createThesisTraceAuth(settings, pool, lifecycle());
      const before = auth.options.databaseHooks?.user?.create?.before;
      const user = {id: "00000000-0000-4000-8000-000000000001", active: true,
        name: "untrusted", email: " Researcher.Label@Example.COM ", emailVerified: false,
        image: null, createdAt: new Date(), updatedAt: new Date()};
      expect(await before?.(user, null)).toBe(false);
      expect(await before?.(user, {path: "/sign-up/email"} as never)).toBe(false);
      expect(await before?.(user, {path: "/sign-in/email-otp"} as never)).toMatchObject({
        data: {email: "researcher.label@example.com", name: "researcher.label", emailVerified: true, active: true},
      });
      expect(auth.options.emailAndPassword?.enabled).toBe(false);
    } finally { await pool.end(); }
  });
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

  it("uses database-backed email OTP and revocable Sessions", async () => {
    const pool = new Pool({ connectionString: settings.databaseUrl });
    try {
      const dependencies = lifecycle();
      const auth = createThesisTraceAuth(settings, pool, dependencies);

      expect(auth.options.baseURL).toBe(settings.publicOrigin);
      expect(auth.options.appName).toBe("QAgentis");
      expect(auth.options.basePath).toBe("/api/auth");
      expect(auth.options.trustedOrigins).toEqual([settings.publicOrigin]);
      expect(auth.options.plugins?.map((plugin) => plugin.id)).toEqual(["email-otp", "oauth-provider", "jwt"]);
      expect(auth.options.emailAndPassword).toEqual({enabled: false});
      expect(auth.options.session).toEqual({
        cookieCache: { enabled: false },
        expiresIn: 60 * 60 * 24 * 7,
        updateAge: 60 * 60 * 24,
      });
      expect(auth.options.disabledPaths).toEqual(
        expect.arrayContaining([
          "/list-accounts",
          "/list-sessions",
          "/reset-password",
          "/sign-in/social",
          "/update-session",
          "/update-user",
        ]),
      );
      expect(auth.options.rateLimit).toMatchObject({
        enabled: true,
        customStorage: { consume: expect.any(Function) },
      });
      expect(auth.options.advanced).toMatchObject({
        backgroundTasks: { handler: dependencies.backgroundTask },
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
        expect(() =>
          createThesisTraceAuth(settings, pool, lifecycle()),
        ).toThrow(name);
      } finally {
        await pool.end();
      }
    },
  );

  it("refuses Session creation when the Researcher is inactive", async () => {
    const isResearcherActive = vi.fn(async () => false);
    const pool = new Pool({ connectionString: settings.databaseUrl });
    try {
      const auth = createThesisTraceAuth(
        settings,
        pool,
        lifecycle({ isResearcherActive }),
      );
      const before = auth.options.databaseHooks?.session?.create?.before;
      const session = {
        createdAt: new Date("2026-08-28T00:00:00.000Z"),
        expiresAt: new Date("2026-09-04T00:00:00.000Z"),
        id: "00000000-0000-4000-8000-000000000002",
        ipAddress: "127.0.0.1",
        token: "secret-session-token",
        updatedAt: new Date("2026-08-28T00:00:00.000Z"),
        userAgent: "test",
        userId: "00000000-0000-4000-8000-000000000001",
      };

      await expect(before?.(session)).rejects.toMatchObject({status: "FORBIDDEN"});
      expect(isResearcherActive).toHaveBeenCalledWith(session.userId);
    } finally {
      await pool.end();
    }
  });
});
