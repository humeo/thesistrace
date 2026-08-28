import { Hono } from "hono";
import { z } from "zod";

import { canonicalizeAuthEmailRequest } from "./identity.js";

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
  "/api/auth/reset-password",
  "/api/auth/sign-in/email",
  "/api/auth/sign-out",
]);

export type AuthAppDependencies = Readonly<{
  authHandler: (request: Request) => Promise<Response> | Response;
  getSession: (input: GetSessionInput) => Promise<unknown>;
  readiness: () => Promise<boolean>;
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
  app.all("/api/auth/*", async (context) => {
    if (!publicBetterAuthPaths.has(context.req.path)) {
      return context.body(null, 404);
    }
    const request = await canonicalizeAuthEmailRequest(context.req.raw);
    if (request instanceof Response) {
      return request;
    }
    return dependencies.authHandler(request);
  });

  return app;
}
