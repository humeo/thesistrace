import { betterAuth } from "better-auth";
import type { Pool } from "pg";

import {
  assertNoAmbientBetterAuthOverrides,
  type AuthSettings,
} from "./config.js";
import { canonicalizeEmail } from "./identity.js";

const DAY_SECONDS = 60 * 60 * 24;
const disabledBetterAuthPaths = [
  "/account-info",
  "/change-email",
  "/delete-user",
  "/delete-user/callback",
  "/error",
  "/get-access-token",
  "/link-social",
  "/list-accounts",
  "/list-sessions",
  "/refresh-token",
  "/reset-password/:token",
  "/revoke-other-sessions",
  "/revoke-session",
  "/revoke-sessions",
  "/send-verification-email",
  "/sign-in/social",
  "/unlink-account",
  "/update-session",
  "/update-user",
  "/verify-email",
  "/verify-password",
] as const;

export function createThesisTraceAuth(settings: AuthSettings, pool: Pool) {
  assertNoAmbientBetterAuthOverrides(process.env);
  return betterAuth({
    advanced: {
      cookiePrefix: "thesistrace",
      database: { generateId: "uuid" },
      defaultCookieAttributes: {
        httpOnly: true,
        path: "/",
        sameSite: "lax",
      },
      disableCSRFCheck: false,
      disableOriginCheck: false,
      ipAddress: {
        ipAddressHeaders: ["x-thesistrace-client-ip"],
      },
      useSecureCookies: settings.secureCookies,
    },
    appName: "ThesisTrace",
    basePath: "/api/auth",
    baseURL: settings.publicOrigin,
    database: pool,
    databaseHooks: {
      user: {
        create: {
          async before(user) {
            const email = canonicalizeEmail(user.email);
            return {
              data: {
                ...user,
                email,
                name: email.slice(0, email.lastIndexOf("@")),
              },
            };
          },
        },
      },
    },
    disabledPaths: [...disabledBetterAuthPaths],
    emailAndPassword: {
      enabled: true,
      maxPasswordLength: 128,
      minPasswordLength: 12,
      requireEmailVerification: false,
    },
    logger: { disabled: true },
    rateLimit: {
      customRules: {
        "/sign-in/email": { max: 5, window: 60 },
        "/sign-up/email": { max: 1, window: 60 },
      },
      enabled: true,
      max: 60,
      storage: "database",
      window: 60,
    },
    secret: settings.secret,
    session: {
      cookieCache: { enabled: false },
      expiresIn: 7 * DAY_SECONDS,
      updateAge: DAY_SECONDS,
    },
    telemetry: { enabled: false },
    trustedOrigins: [settings.publicOrigin],
    user: {
      additionalFields: {
        active: {
          defaultValue: true,
          input: false,
          required: true,
          type: "boolean",
        },
      },
      changeEmail: { enabled: false },
      deleteUser: { enabled: false },
    },
  });
}

export type ThesisTraceAuth = ReturnType<typeof createThesisTraceAuth>;
