import { betterAuth } from "better-auth";
import type { Pool } from "pg";

import {
  assertNoAmbientBetterAuthOverrides,
  type AuthSettings,
} from "./config.js";
import { canonicalizeEmail } from "./identity.js";
import { InvitationAdmission } from "./invitation-admission.js";
import {
  passwordResetIdentifier,
  rawPasswordResetToken,
} from "./password-reset-token.js";
import { sha256 } from "./security.js";

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

type PasswordResetUser = Readonly<{
  email: string;
  id: string;
  name: string;
}>;

export type AuthLifecycleDependencies = Readonly<{
  backgroundTask: (promise: Promise<unknown>) => void;
  invitationAdmission: InvitationAdmission;
  isResearcherActive: (userId: string) => Promise<boolean>;
  recordPasswordResetCredential: (input: Readonly<{
    identifier: string;
    researcherId: string;
    tokenHash: Buffer;
  }>) => void;
  recordSession: (input: Readonly<{
    researcherId: string;
    token: string;
  }>) => void;
  sendResetPassword: (
    data: Readonly<{
      token: string;
      url: string;
      user: PasswordResetUser;
    }>,
    request?: Request,
  ) => Promise<void>;
}>;

export function createClosedAuthLifecycle(): AuthLifecycleDependencies {
  return {
    backgroundTask(promise) {
      void promise.catch(() => undefined);
    },
    invitationAdmission: new InvitationAdmission(),
    async isResearcherActive() {
      return false;
    },
    recordPasswordResetCredential() {},
    recordSession() {},
    async sendResetPassword() {
      throw new Error("PASSWORD_RESET_DELIVERY_UNAVAILABLE");
    },
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
    appName: "ThesisTrace",
    basePath: "/api/auth",
    baseURL: settings.publicOrigin,
    database: pool,
    databaseHooks: {
      verification: {
        create: {
          async before(verification) {
            const token = rawPasswordResetToken(verification.identifier);
            if (token === null) return true;
            const identifier = passwordResetIdentifier(token);
            lifecycle.recordPasswordResetCredential({
              identifier,
              researcherId: verification.value,
              tokenHash: sha256(token),
            });
            return {
              data: {
                ...verification,
                identifier,
              },
            };
          },
        },
      },
      user: {
        create: {
          async before(user) {
            const email = canonicalizeEmail(user.email);
            if (!lifecycle.invitationAdmission.allows(email)) {
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
              !lifecycle.invitationAdmission.isActive()
              && !(await lifecycle.isResearcherActive(session.userId))
            ) {
              return false;
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
    emailAndPassword: {
      enabled: true,
      maxPasswordLength: 128,
      minPasswordLength: 12,
      requireEmailVerification: false,
      resetPasswordTokenExpiresIn: 30 * 60,
      sendResetPassword: lifecycle.sendResetPassword,
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
