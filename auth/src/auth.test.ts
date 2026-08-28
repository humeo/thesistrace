import { Pool } from "pg";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createThesisTraceAuth,
  type AuthLifecycleDependencies,
} from "./auth.js";
import type { AuthSettings } from "./config.js";
import { InvitationAdmission } from "./invitation-admission.js";

const settings: AuthSettings = {
  databaseUrl: "postgresql://auth_runtime:password@127.0.0.1:5432/thesistrace",
  environment: "test",
  host: "127.0.0.1",
  port: 8200,
  publicOrigin: "http://127.0.0.1:5173",
  resendApiKey: "test-resend-key",
  resendApiUrl: "http://127.0.0.1:8300",
  resendFromEmail: "ThesisTrace <noreply@thesistrace.test>",
  secret: "0123456789abcdef0123456789abcdef",
  secureCookies: false,
};

function lifecycle(
  overrides: Partial<AuthLifecycleDependencies> = {},
): AuthLifecycleDependencies {
  return {
    backgroundTask: vi.fn(),
    invitationAdmission: new InvitationAdmission(),
    isResearcherActive: vi.fn(async () => true),
    sendResetPassword: vi.fn(async () => undefined),
    ...overrides,
  };
}

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
      const dependencies = lifecycle();
      const auth = createThesisTraceAuth(settings, pool, dependencies);

      expect(auth.options.baseURL).toBe(settings.publicOrigin);
      expect(auth.options.basePath).toBe("/api/auth");
      expect(auth.options.trustedOrigins).toEqual([settings.publicOrigin]);
      expect("plugins" in auth.options).toBe(false);
      expect(auth.options.emailAndPassword).toMatchObject({
        enabled: true,
        maxPasswordLength: 128,
        minPasswordLength: 12,
        resetPasswordTokenExpiresIn: 30 * 60,
      });
      expect(auth.options.emailAndPassword?.sendResetPassword).toBe(
        dependencies.sendResetPassword,
      );
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
        storage: "database",
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

  it("creates a Researcher only inside the matching Invitation admission scope", async () => {
    const pool = new Pool({ connectionString: settings.databaseUrl });
    const invitationAdmission = new InvitationAdmission();
    try {
      const auth = createThesisTraceAuth(
        settings,
        pool,
        lifecycle({ invitationAdmission }),
      );
      const before = auth.options.databaseHooks?.user?.create?.before;
      expect(before).toBeDefined();
      const user = {
        active: true,
        createdAt: new Date("2026-08-28T00:00:00.000Z"),
        email: " Researcher.Label@Example.COM ",
        emailVerified: false,
        id: "00000000-0000-4000-8000-000000000001",
        image: null,
        name: "untrusted label",
        updatedAt: new Date("2026-08-28T00:00:00.000Z"),
      };

      expect(await before?.(user)).toBe(false);
      await invitationAdmission.run("researcher.label@example.com", async () => {
        expect(await before?.(user)).toMatchObject({
          data: {
            active: true,
            email: "researcher.label@example.com",
            emailVerified: true,
            name: "researcher.label",
          },
        });
      });
      await invitationAdmission.run("other@example.com", async () => {
        expect(await before?.(user)).toBe(false);
      });
    } finally {
      await pool.end();
    }
  });

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

      expect(await before?.(session)).toBe(false);
      expect(isResearcherActive).toHaveBeenCalledWith(session.userId);
    } finally {
      await pool.end();
    }
  });
});
