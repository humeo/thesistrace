import { oauthProvider } from "@better-auth/oauth-provider";
import { mcpOAuthOptions } from "./mcp-oauth.js";
import { betterAuth } from "better-auth";
import { emailOTP } from "better-auth/plugins/email-otp";
import { APIError } from "better-auth/api";
import { jwt } from "better-auth/plugins";
import type { Pool } from "pg";

import {
  assertNoAmbientBetterAuthOverrides,
  type AuthSettings,
} from "./config.js";
import { createBetterAuthRateLimitStorage } from "./auth-rate-limit.js";
import { canonicalizeEmail } from "./identity.js";

const DAY_SECONDS = 60 * 60 * 24;
const disabledBetterAuthPaths = [
  "/sign-up/email",
  "/sign-in/email",
  "/request-password-reset",
  "/change-password",
  "/set-password",
  "/token",
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
  "/reset-password",
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

export type AuthLifecycleDependencies = Readonly<{
  backgroundTask: (promise: Promise<unknown>) => void;
  isResearcherActive: (userId: string) => Promise<boolean>;
  recordSession: (input: Readonly<{
    researcherId: string;
    token: string;
  }>) => void;
}>;

export function createClosedAuthLifecycle(): AuthLifecycleDependencies {
  return {
    backgroundTask(promise) {
      void promise.catch(() => undefined);
    },
    async isResearcherActive() {
      return false;
    },
    recordSession() {},
  };
}

export function createThesisTraceAuth(
  settings: AuthSettings,
  pool: Pool,
  lifecycle: AuthLifecycleDependencies,
) {
  assertNoAmbientBetterAuthOverrides(process.env);
  return betterAuth({
    advanced: {
      backgroundTasks: { handler: lifecycle.backgroundTask },
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
    appName: "QAgentis",
    basePath: "/api/auth",
    baseURL: settings.publicOrigin,
    database: pool,
    databaseHooks: {
      user: {
        create: {
          async before(user, context) {
            const email = canonicalizeEmail(user.email);
            if (context?.path !== "/sign-in/email-otp") {
              return false;
            }
            return {
              data: {
                ...user,
                active: true,
                email,
                emailVerified: true,
                name: email.slice(0, email.lastIndexOf("@")),
              },
            };
          },
        },
      },
      session: {
        create: {
          async before(session) {
            if (
              !(await lifecycle.isResearcherActive(session.userId))
            ) {
              throw new APIError("FORBIDDEN", {
                code: "ACCOUNT_INACTIVE",
                message: "This account is inactive.",
              });
            }
            lifecycle.recordSession({
              researcherId: session.userId,
              token: session.token,
            });
            return true;
          },
        },
      },
    },
    disabledPaths: [...disabledBetterAuthPaths],
    emailAndPassword: { enabled: false },
    logger: { disabled: true },
    plugins: [
      emailOTP({
        otpLength: 6,
        expiresIn: 300,
        allowedAttempts: 3,
        storeOTP: "hashed",
        disableSignUp: false,
        resendStrategy: "rotate",
        // The plugin swallows background delivery failures. Our HTTP issuance
        // uses EmailCodeDelivery so a failed delivery cannot report success.
        async sendVerificationOTP() {
          throw new Error("USE_EMAIL_CODE_DELIVERY");
        },
      }),
      oauthProvider(mcpOAuthOptions(settings, lifecycle.isResearcherActive)),
      jwt({
        adapter: {
          async createJwk() {
            throw new Error("STATIC_MCP_SIGNING_KEY_REQUIRED");
          },
          async getJwks() {
            return [{
              alg: "EdDSA",
              createdAt: new Date(0),
              crv: "Ed25519",
              id: settings.mcpPrivateJwk.kid,
              privateKey: JSON.stringify(settings.mcpPrivateJwk),
              publicKey: JSON.stringify(settings.mcpPublicJwk),
            }];
          },
        },
        disableSettingJwtHeader: true,
        jwks: {
          disablePrivateKeyEncryption: true,
          keyPairConfig: { alg: "EdDSA", crv: "Ed25519" },
        },
        jwt: {
          audience: settings.mcpAudience,
          expirationTime: `${settings.mcpTokenLifetimeSeconds} seconds`,
          issuer: settings.mcpIssuer,
        },
      }),
    ],
    rateLimit: {
      customRules: {
        // Automatic Session checks must stay available during continuous activity.
        // Session verification remains mandatory; this is only an HTTP quota exemption.
        "/get-session": false,
        "/sign-in/email-otp": { max: 5, window: 60 },
      },
      enabled: true,
      max: 60,
      customStorage: createBetterAuthRateLimitStorage({ pool }),
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
