import { Hono, type Context } from "hono";
import { z } from "zod";

import {
  ResearcherNotFoundError,
  type ResearcherSessionRevocationResult,
} from "./access.js";
import {
  canonicalizeAuthEmailRequest,
  canonicalizeEmail,
  InvalidEmailError,
} from "./identity.js";
import { isJsonContentType } from "./http-media-type.js";
import type { AuthHttpObserver } from "./http-observability.js";
import {
  InvitationConflictError,
  InvitationDeliveryError,
  InvitationRejectedError,
} from "./invitation.js";
import {
  OperatorAccessNotFoundError,
  OperatorCursorInvalidError,
  type OperatorInvitationSummary,
  type OperatorPage,
  type OperatorPrincipal,
  OperatorQueryInvalidError,
  type OperatorResearcherSummary,
} from "./operator-directory.js";
import { PasswordResetRejectedError } from "./password-reset.js";
import {
  OperatorPasswordInvalidError,
  OperatorProofInvalidError,
  OperatorProofNotFoundError,
  isIsoResearchSession,
  isMarketRefreshIdempotencyKey,
  type OperatorProofRequest,
} from "./operator-proof.js";
import { OperatorSessionTargetProtectedError } from "./operator-session-revocation.js";

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
const operatorProofSchema = z.union([
  z
    .object({
      email: z.string().min(1).max(512),
      operation: z.enum(["invitation.issue", "invitation.reissue"]),
      password: z.string().min(12).max(128),
    })
    .strict(),
  z
    .object({
      operation: z.literal("researcher.sessions.revoke"),
      password: z.string().min(12).max(128),
      researcher_id: z.uuid(),
    })
    .strict(),
  z
    .object({
      as_of: z.string().min(1).max(128).refine((value) => value === value.trim()),
      idempotency_key: z.string().refine(isMarketRefreshIdempotencyKey),
      operation: z.literal("data.refresh.market.submit"),
      password: z.string().min(12).max(128),
    })
    .strict(),
  z
    .object({
      idempotency_key: z.string().refine(isMarketRefreshIdempotencyKey),
      observation_through_session: z.string().refine(isIsoResearchSession),
      operation: z.literal("data.refresh.financial.submit"),
      password: z.string().min(12).max(128),
    })
    .strict(),
]);
const internalOperatorProofConsumptionSchema = z.union([
  z
    .object({
      as_of: z.string().min(1).max(128).refine((value) => value === value.trim()),
      idempotency_key: z.string().refine(isMarketRefreshIdempotencyKey),
      operation: z.literal("data.refresh.market.submit"),
      proof: z.string().length(80),
    })
    .strict(),
  z
    .object({
      idempotency_key: z.string().refine(isMarketRefreshIdempotencyKey),
      observation_through_session: z.string().refine(isIsoResearchSession),
      operation: z.literal("data.refresh.financial.submit"),
      proof: z.string().length(80),
    })
    .strict(),
]);
const operatorInvitationMutationSchema = z
  .object({
    email: z.string().min(1).max(512),
    proof: z.string().length(80),
  })
  .strict();
const operatorSessionRevocationSchema = z
  .object({
    proof: z.string().length(80),
    researcher_id: z.uuid(),
  })
  .strict();

const verifiedSessionSchema = z.object({
  session: z.object({ id: z.uuid() }).passthrough(),
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
  consumeOperatorProofRateLimit: (
    sessionId: string,
    headers: Headers,
  ) => Promise<Readonly<{ allowed: boolean; retryAfterSeconds: number }>>;
  consumePasswordResetRateLimit: (
    token: string,
    headers: Headers,
  ) => Promise<Readonly<{ allowed: boolean; retryAfterSeconds: number }>>;
  getSession: (input: GetSessionInput) => Promise<unknown>;
  hasOperatorCapability: (principal: OperatorPrincipal) => Promise<boolean>;
  httpObserver?: AuthHttpObserver;
  inspectInvitation: (token: string) => Promise<Readonly<{ email: string }>>;
  confirmOperatorProof: (
    principal: OperatorPrincipal,
    input: OperatorProofRequest & Readonly<{ password: string }>,
  ) => Promise<Readonly<{ expiresAt: string; proof: string }>>;
  consumeOperatorProof: (
    principal: OperatorPrincipal,
    input: OperatorProofRequest & Readonly<{ proof: string }>,
  ) => Promise<void>;
  issueOperatorInvitation: (
    principal: OperatorPrincipal,
    input: Readonly<{ email: string; proof: string }>,
  ) => Promise<Readonly<{
    email: string;
    invitationId: string;
    status: "delivered";
  }>>;
  listOperatorInvitations: (
    principal: OperatorPrincipal,
    input: Readonly<{ cursor: string | null }>,
  ) => Promise<OperatorPage<OperatorInvitationSummary>>;
  listOperatorResearchers: (
    principal: OperatorPrincipal,
    input: Readonly<{ cursor: string | null; search: string | null }>,
  ) => Promise<OperatorPage<OperatorResearcherSummary>>;
  publicOrigin: string;
  readiness: () => Promise<boolean>;
  reissueOperatorInvitation: (
    principal: OperatorPrincipal,
    input: Readonly<{ email: string; proof: string }>,
  ) => Promise<Readonly<{
    email: string;
    invitationId: string;
    status: "delivered";
  }>>;
  revokeOperatorResearcherSessions: (
    principal: OperatorPrincipal,
    input: Readonly<{ proof: string; researcherId: string }>,
  ) => Promise<ResearcherSessionRevocationResult>;
  resetPassword: (token: string, newPassword: string) => Promise<void>;
}>;

export function createAuthApp(dependencies: AuthAppDependencies): Hono {
  const app = new Hono();
  app.use("*", async (context, next) => {
    const observer = dependencies.httpObserver;
    if (observer === undefined || context.req.path.startsWith("/health/")) {
      await next();
      return;
    }
    const observation = observer.start(context.req.raw.headers);
    await next();
    context.header("X-Request-ID", observation.requestId);
    observer.complete(observation, {
      method: context.req.method,
      path: context.req.path,
      status: context.res.status,
    });
  });
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

  app.get("/internal/operator/page-access", async (context) => {
    const principal = await requireOperator(
      dependencies,
      context.req.raw.headers,
    );
    if (principal instanceof Response) return principal;
    return context.body(null, 204);
  });

  app.post("/internal/operator/proofs/consume", async (context) => {
    const principal = await requireOperator(
      dependencies,
      context.req.raw.headers,
    );
    if (principal instanceof Response) return principal;
    const body = await exactJson(
      context.req.raw,
      internalOperatorProofConsumptionSchema,
    );
    if (body === null) {
      return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
    }
    try {
      await dependencies.consumeOperatorProof(
        principal,
        body.operation === "data.refresh.market.submit"
          ? {
              asOf: body.as_of,
              idempotencyKey: body.idempotency_key,
              operation: body.operation,
              proof: body.proof,
            }
          : {
              idempotencyKey: body.idempotency_key,
              observationThroughSession: body.observation_through_session,
              operation: body.operation,
              proof: body.proof,
            },
      );
      return context.body(null, 204);
    } catch (error) {
      if (error instanceof OperatorProofInvalidError) {
        return context.json({ code: "OPERATOR_PROOF_INVALID" }, 400);
      }
      throw error;
    }
  });

  app.get("/api/auth/operator/capability", async (context) => {
    const principal = await requireOperator(
      dependencies,
      context.req.raw.headers,
    );
    if (principal instanceof Response) return principal;
    return context.json({ operator: true as const });
  });

  app.get("/api/auth/operator/researchers", async (context) => {
    const principal = await requireOperator(
      dependencies,
      context.req.raw.headers,
    );
    if (principal instanceof Response) return principal;
    const query = exactQuery(context.req.url, new Set(["cursor", "search"]));
    if (query === null) {
      return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
    }
    try {
      const page = await dependencies.listOperatorResearchers(principal, {
        cursor: query.get("cursor"),
        search: query.get("search"),
      });
      return context.json({
        items: page.items.map(researcherResponse),
        next_cursor: page.nextCursor,
      });
    } catch (error) {
      return operatorReadError(error);
    }
  });

  app.get("/api/auth/operator/invitations", async (context) => {
    const principal = await requireOperator(
      dependencies,
      context.req.raw.headers,
    );
    if (principal instanceof Response) return principal;
    const query = exactQuery(context.req.url, new Set(["cursor"]));
    if (query === null) {
      return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
    }
    try {
      const page = await dependencies.listOperatorInvitations(principal, {
        cursor: query.get("cursor"),
      });
      return context.json({
        items: page.items.map(invitationResponse),
        next_cursor: page.nextCursor,
      });
    } catch (error) {
      return operatorReadError(error);
    }
  });

  app.post("/api/auth/operator/proofs", async (context) => {
    const principal = await requireOperator(
      dependencies,
      context.req.raw.headers,
    );
    if (principal instanceof Response) return principal;
    if (context.req.header("origin") !== dependencies.publicOrigin) {
      return context.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
    }
    const body = await exactJson(context.req.raw, operatorProofSchema);
    if (body === null) {
      return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
    }
    const rateLimit = await dependencies.consumeOperatorProofRateLimit(
      principal.sessionId,
      context.req.raw.headers,
    );
    if (!rateLimit.allowed) {
      context.header("retry-after", String(rateLimit.retryAfterSeconds));
      return context.json({ code: "AUTH_RATE_LIMITED" }, 429);
    }
    try {
      const result = await dependencies.confirmOperatorProof(
        principal,
        body.operation === "researcher.sessions.revoke"
          ? {
              operation: body.operation,
              password: body.password,
              researcherId: body.researcher_id,
            }
          : body.operation === "data.refresh.market.submit"
            ? {
                asOf: body.as_of,
                idempotencyKey: body.idempotency_key,
                operation: body.operation,
                password: body.password,
              }
            : body.operation === "data.refresh.financial.submit"
              ? {
                  idempotencyKey: body.idempotency_key,
                  observationThroughSession: body.observation_through_session,
                  operation: body.operation,
                  password: body.password,
                }
          : {
              email: canonicalizeEmail(body.email),
              operation: body.operation,
              password: body.password,
            },
      );
      return context.json({
        expires_at: result.expiresAt,
        proof: result.proof,
      });
    } catch (error) {
      if (error instanceof OperatorProofNotFoundError) {
        return context.body(null, 404);
      }
      if (error instanceof OperatorPasswordInvalidError) {
        return context.json({ code: "OPERATOR_PASSWORD_INVALID" }, 400);
      }
      if (error instanceof InvalidEmailError) {
        return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
      }
      if (error instanceof OperatorProofInvalidError) {
        return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
      }
      throw error;
    }
  });

  app.post("/api/auth/operator/invitations/issue", async (context) =>
    operatorInvitationMutation(context, dependencies, "issue")
  );
  app.post("/api/auth/operator/invitations/reissue", async (context) =>
    operatorInvitationMutation(context, dependencies, "reissue")
  );
  app.post(
    "/api/auth/operator/researchers/sessions/revoke",
    async (context) => operatorSessionRevocation(context, dependencies),
  );

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

async function operatorSessionRevocation(
  context: Context,
  dependencies: AuthAppDependencies,
): Promise<Response> {
  const principal = await requireOperator(
    dependencies,
    context.req.raw.headers,
  );
  if (principal instanceof Response) return principal;
  if (context.req.header("origin") !== dependencies.publicOrigin) {
    return context.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
  }
  const body = await exactJson(
    context.req.raw,
    operatorSessionRevocationSchema,
  );
  if (body === null) {
    return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
  }
  try {
    const result = await dependencies.revokeOperatorResearcherSessions(
      principal,
      { proof: body.proof, researcherId: body.researcher_id },
    );
    return context.json({
      researcher_id: result.researcherId,
      revoked_session_count: result.revokedSessionCount,
      status: result.status,
    });
  } catch (error) {
    if (error instanceof OperatorProofNotFoundError) {
      return context.body(null, 404);
    }
    if (error instanceof OperatorProofInvalidError) {
      return context.json({ code: "OPERATOR_PROOF_INVALID" }, 400);
    }
    if (error instanceof OperatorSessionTargetProtectedError) {
      return context.json(
        { code: "OPERATOR_SESSION_TARGET_PROTECTED" },
        409,
      );
    }
    if (error instanceof ResearcherNotFoundError) {
      return context.json({ code: "OPERATOR_SESSION_TARGET_INVALID" }, 409);
    }
    throw error;
  }
}

async function operatorInvitationMutation(
  context: Context,
  dependencies: AuthAppDependencies,
  operation: "issue" | "reissue",
): Promise<Response> {
  const principal = await requireOperator(
    dependencies,
    context.req.raw.headers,
  );
  if (principal instanceof Response) return principal;
  if (context.req.header("origin") !== dependencies.publicOrigin) {
    return context.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
  }
  const body = await exactJson(
    context.req.raw,
    operatorInvitationMutationSchema,
  );
  if (body === null) {
    return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
  }
  try {
    const input = { email: canonicalizeEmail(body.email), proof: body.proof };
    const result = operation === "issue"
      ? await dependencies.issueOperatorInvitation(principal, input)
      : await dependencies.reissueOperatorInvitation(principal, input);
    return context.json({
      email: result.email,
      invitation_id: result.invitationId,
      status: result.status,
    });
  } catch (error) {
    if (error instanceof OperatorProofNotFoundError) {
      return context.body(null, 404);
    }
    if (error instanceof OperatorProofInvalidError) {
      return context.json({ code: "OPERATOR_PROOF_INVALID" }, 400);
    }
    if (error instanceof InvalidEmailError) {
      return context.json({ code: "OPERATOR_REQUEST_INVALID" }, 400);
    }
    if (error instanceof InvitationConflictError) {
      return context.json({ code: "OPERATOR_INVITATION_CONFLICT" }, 409);
    }
    if (error instanceof InvitationDeliveryError) {
      return context.json(
        { code: "OPERATOR_INVITATION_DELIVERY_FAILED" },
        502,
      );
    }
    throw error;
  }
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
  if (!isJsonContentType(request.headers.get("content-type"))) {
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
  if (!isJsonContentType(request.headers.get("content-type"))) {
    return null;
  }
  try {
    const parsed = schema.safeParse(await request.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

async function requireOperator(
  dependencies: AuthAppDependencies,
  headers: Headers,
): Promise<OperatorPrincipal | Response> {
  let session: unknown;
  try {
    session = await dependencies.getSession({
      headers,
      query: { disableCookieCache: true, disableRefresh: true },
    });
  } catch {
    return Response.json(
      { code: "AUTH_SERVICE_UNAVAILABLE" },
      { status: 503 },
    );
  }
  if (session === null) return new Response(null, { status: 404 });
  const parsed = verifiedSessionSchema.safeParse(session);
  if (!parsed.success) {
    return Response.json(
      { code: "AUTH_SERVICE_UNAVAILABLE" },
      { status: 503 },
    );
  }
  if (!parsed.data.user.active) return new Response(null, { status: 404 });
  const principal = {
    researcherId: parsed.data.user.id,
    sessionId: parsed.data.session.id,
  };
  if (!(await dependencies.hasOperatorCapability(principal))) {
    return new Response(null, { status: 404 });
  }
  return principal;
}

function exactQuery(
  url: string,
  allowed: ReadonlySet<string>,
): URLSearchParams | null {
  const query = new URL(url).searchParams;
  const seen = new Set<string>();
  for (const name of query.keys()) {
    if (!allowed.has(name) || seen.has(name)) return null;
    seen.add(name);
  }
  return query;
}

function operatorReadError(error: unknown): Response {
  if (error instanceof OperatorAccessNotFoundError) {
    return new Response(null, { status: 404 });
  }
  if (
    error instanceof OperatorCursorInvalidError
    || error instanceof OperatorQueryInvalidError
  ) {
    return Response.json(
      { code: "OPERATOR_REQUEST_INVALID" },
      { status: 400 },
    );
  }
  throw error;
}

function researcherResponse(item: OperatorResearcherSummary) {
  return {
    active: item.active,
    created_at: item.createdAt,
    current_session_count: item.currentSessionCount,
    display_label: item.displayLabel,
    effective_invitation:
      item.effectiveInvitation === null
        ? null
        : invitationResponse(item.effectiveInvitation),
    email: item.email,
    latest_successful_login_at: item.latestSuccessfulLoginAt,
    researcher_id: item.id,
  };
}

function invitationResponse(item: OperatorInvitationSummary) {
  return {
    created_at: item.createdAt,
    delivered_at: item.deliveredAt,
    effective: item.effective,
    email: item.email,
    expires_at: item.expiresAt,
    invitation_id: item.id,
    researcher_id: item.researcherId,
    status: item.status,
    terminal_at: item.terminalAt,
  };
}
