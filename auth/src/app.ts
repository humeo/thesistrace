import { Hono } from "hono";
import { z } from "zod";

import { canonicalizeAuthEmailRequest } from "./identity.js";
import { InvitationRejectedError } from "./invitation.js";
import { PasswordResetRejectedError } from "./password-reset.js";

const invitationInspectSchema = z
  .object({ token: z.string().length(80) })
  .strict();
const invitationAcceptSchema = z
  .object({
    password: z.string().min(12).max(128),
    token: z.string().length(80),
  })
  .strict();
const signInSchema = z
  .object({ email: z.email(), password: z.string().min(12).max(128) })
  .strict();
const requestPasswordResetSchema = z.object({ email: z.email() }).strict();
const resetPasswordSchema = z
  .object({
    newPassword: z.string().min(12).max(128),
    token: z.string().min(1).max(512),
  })
  .strict();
const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(12).max(128),
    newPassword: z.string().min(12).max(128),
  })
  .strict();

const verifiedSessionSchema = z.object({
  session: z.object({}).passthrough(),
  user: z.object({
    active: z.boolean(),
    email: z.email(),
    id: z.uuid(),
    name: z.string().min(1),
  }),
});

type GetSessionInput = Readonly<{
  headers: Headers;
  query: Readonly<{
    disableCookieCache: true;
    disableRefresh: true;
  }>;
}>;

const publicBetterAuthPaths = new Set([
  "/api/auth/change-password",
  "/api/auth/get-session",
  "/api/auth/ok",
  "/api/auth/request-password-reset",
  "/api/auth/sign-in/email",
  "/api/auth/sign-out",
]);

export type AuthAppDependencies = Readonly<{
  acceptInvitation: (
    token: string,
    password: string,
    headers: Headers,
  ) => Promise<Readonly<{ setCookies: string[] }>>;
  authHandler: (request: Request) => Promise<Response> | Response;
  consumeInvitationRateLimit: (
    token: string,
    headers: Headers,
  ) => Promise<Readonly<{ allowed: boolean; retryAfterSeconds: number }>>;
  consumePasswordResetRateLimit: (
    token: string,
    headers: Headers,
  ) => Promise<Readonly<{ allowed: boolean; retryAfterSeconds: number }>>;
  getSession: (input: GetSessionInput) => Promise<unknown>;
  inspectInvitation: (token: string) => Promise<Readonly<{ email: string }>>;
  publicOrigin: string;
  readiness: () => Promise<boolean>;
  resetPassword: (token: string, newPassword: string) => Promise<void>;
}>;

export function createAuthApp(dependencies: AuthAppDependencies): Hono {
  const app = new Hono();
  app.onError((_error, context) =>
    context.json({ code: "AUTH_SERVICE_UNAVAILABLE" }, 503),
  );

  app.get("/health/live", (context) => context.json({ status: "ok" }));
  app.get("/health/ready", async (context) => {
    try {
      const ready = await dependencies.readiness();
      return context.json(
        { status: ready ? "ready" : "unavailable" },
        ready ? 200 : 503,
      );
    } catch {
      return context.json({ status: "unavailable" }, 503);
    }
  });

  app.post("/internal/session/verify", async (context) => {
    let session: unknown;
    try {
      session = await dependencies.getSession({
        headers: context.req.raw.headers,
        query: { disableCookieCache: true, disableRefresh: true },
      });
    } catch {
      return context.json({ code: "AUTH_SERVICE_UNAVAILABLE" }, 503);
    }
    if (session === null) {
      return context.json({ code: "AUTHENTICATION_REQUIRED" }, 401);
    }
    const parsed = verifiedSessionSchema.safeParse(session);
    if (!parsed.success) {
      return context.json({ code: "AUTH_SERVICE_UNAVAILABLE" }, 503);
    }
    if (!parsed.data.user.active) {
      return context.json({ code: "AUTHENTICATION_REQUIRED" }, 401);
    }
    return context.json({
      active: true as const,
      display_label: parsed.data.user.name,
      email: parsed.data.user.email,
      researcher_id: parsed.data.user.id,
    });
  });

  app.post("/api/auth/sign-up/email", (context) =>
    context.json({ code: "RESEARCHER_INVITATION_REQUIRED" }, 403),
  );
  app.post("/api/auth/reset-password", async (context) => {
    if (context.req.header("origin") !== dependencies.publicOrigin) {
      return context.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
    }
    const body = await exactJson(context.req.raw, resetPasswordSchema);
    if (body === null) {
      return context.json({ code: "AUTH_REQUEST_INVALID" }, 400);
    }
    const rateLimit = await dependencies.consumePasswordResetRateLimit(
      body.token,
      context.req.raw.headers,
    );
    if (!rateLimit.allowed) {
      context.header("retry-after", String(rateLimit.retryAfterSeconds));
      return context.json({ code: "AUTH_RATE_LIMITED" }, 429);
    }
    try {
      await dependencies.resetPassword(body.token, body.newPassword);
      return context.json({ status: true as const });
    } catch (error) {
      if (error instanceof PasswordResetRejectedError) {
        return context.json({ code: "AUTH_REQUEST_INVALID" }, 400);
      }
      throw error;
    }
  });
  app.post("/api/auth/researcher-invitation/inspect", async (context) => {
    if (context.req.header("origin") !== dependencies.publicOrigin) {
      return context.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
    }
    const body = await exactJson(context.req.raw, invitationInspectSchema);
    if (body === null) {
      return context.json({ code: "INVITATION_INVALID" }, 400);
    }
    const rateLimit = await dependencies.consumeInvitationRateLimit(
      body.token,
      context.req.raw.headers,
    );
    if (!rateLimit.allowed) {
      context.header("retry-after", String(rateLimit.retryAfterSeconds));
      return context.json({ code: "AUTH_RATE_LIMITED" }, 429);
    }
    try {
      return context.json(await dependencies.inspectInvitation(body.token));
    } catch (error) {
      if (error instanceof InvitationRejectedError) {
        return context.json({ code: "INVITATION_INVALID" }, 400);
      }
      throw error;
    }
  });
  app.post("/api/auth/researcher-invitation/accept", async (context) => {
    if (context.req.header("origin") !== dependencies.publicOrigin) {
      return context.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
    }
    const body = await exactJson(context.req.raw, invitationAcceptSchema);
    if (body === null) {
      return context.json({ code: "INVITATION_INVALID" }, 400);
    }
    const rateLimit = await dependencies.consumeInvitationRateLimit(
      body.token,
      context.req.raw.headers,
    );
    if (!rateLimit.allowed) {
      context.header("retry-after", String(rateLimit.retryAfterSeconds));
      return context.json({ code: "AUTH_RATE_LIMITED" }, 429);
    }
    try {
      const accepted = await dependencies.acceptInvitation(
        body.token,
        body.password,
        context.req.raw.headers,
      );
      for (const cookie of accepted.setCookies) {
        context.header("set-cookie", cookie, { append: true });
      }
      return context.json({ status: true as const });
    } catch (error) {
      if (error instanceof InvitationRejectedError) {
        return context.json({ code: "INVITATION_INVALID" }, 400);
      }
      throw error;
    }
  });
  app.all("/api/auth/*", async (context) => {
    if (!publicBetterAuthPaths.has(context.req.path)) {
      return context.body(null, 404);
    }
    const request = await canonicalizeAuthEmailRequest(context.req.raw);
    if (request instanceof Response) {
      return request;
    }
    const normalizedRequest = await normalizePublicAuthRequest(request);
    if (normalizedRequest instanceof Response) {
      return normalizedRequest;
    }
    return dependencies.authHandler(normalizedRequest);
  });

  return app;
}

async function normalizePublicAuthRequest(
  request: Request,
): Promise<Request | Response> {
  if (request.method !== "POST") {
    return request;
  }
  const path = new URL(request.url).pathname;
  const schema =
    path === "/api/auth/sign-in/email"
      ? signInSchema
      : path === "/api/auth/request-password-reset"
        ? requestPasswordResetSchema
        : path === "/api/auth/change-password"
          ? changePasswordSchema
          : null;
  if (schema === null) {
    return request;
  }
  if (
    !request.headers
      .get("content-type")
      ?.toLowerCase()
      .startsWith("application/json")
  ) {
    return Response.json({ code: "AUTH_REQUEST_INVALID" }, { status: 400 });
  }
  try {
    const parsed = schema.safeParse(await request.clone().json());
    if (!parsed.success) {
      return Response.json({ code: "AUTH_REQUEST_INVALID" }, { status: 400 });
    }
    const body =
      path === "/api/auth/change-password"
        ? { ...parsed.data, revokeOtherSessions: true }
        : parsed.data;
    const headers = new Headers(request.headers);
    headers.delete("content-length");
    return new Request(request, { body: JSON.stringify(body), headers });
  } catch {
    return Response.json({ code: "AUTH_REQUEST_INVALID" }, { status: 400 });
  }
}

async function exactJson<T>(
  request: Request,
  schema: z.ZodType<T>,
): Promise<T | null> {
  if (
    !request.headers
      .get("content-type")
      ?.toLowerCase()
      .startsWith("application/json")
  ) {
    return null;
  }
  try {
    const parsed = schema.safeParse(await request.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}
