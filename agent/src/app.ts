import { Hono } from "hono";
import { bodyLimit } from "hono/body-limit";

import { AgentAuthenticationUnavailableError } from "./failure.js";
import { isChatThreadId } from "./chat-request.js";
import type { SafeModelCatalog } from "./model-registry.js";
import {
  MAX_SESSION_RENAME_BODY_BYTES,
  SessionInputError,
  readRenameSessionInput,
  readSessionCursor,
  type SessionCursor,
} from "./session-management.js";
import {
  SessionActiveRunError,
  SessionNotFoundError,
  SessionVersionConflictError,
  type RenamedSession,
  type SessionPage,
} from "./session-repository.js";
import type { VerifiedResearcher } from "./session-verifier.js";

export type AgentAppDependencies = Readonly<{
  deleteSession: (
    threadId: string,
    researcher: VerifiedResearcher,
  ) => Promise<void>;
  handleRuntime: (
    request: Request,
    researcher: VerifiedResearcher,
  ) => Promise<Response>;
  modelCatalog: SafeModelCatalog;
  publicOrigin: string;
  readiness?: () => Promise<boolean>;
  renameSession: (
    threadId: string,
    researcher: VerifiedResearcher,
    title: string,
    expectedVersion: Date,
  ) => Promise<RenamedSession>;
  session: (
    threadId: string,
    researcher: VerifiedResearcher,
  ) => Promise<SessionPage["sessions"][number]>;
  sessions: (
    cursor: SessionCursor | undefined,
    researcher: VerifiedResearcher,
  ) => Promise<SessionPage>;
  sessionPreference: (
    threadId: string,
    researcher: VerifiedResearcher,
  ) => Promise<Readonly<{ model_key: string; reasoning_effort: string }> | null>;
  verifySession: (headers: Headers) => Promise<VerifiedResearcher | null>;
}>;

type AgentAppEnvironment = Readonly<{
  Variables: Readonly<{ researcher: VerifiedResearcher }>;
}>;

export function createAgentApp(dependencies: AgentAppDependencies): Hono<AgentAppEnvironment> {
  const app = new Hono<AgentAppEnvironment>();
  app.onError((_error, context) =>
    context.json({ code: "AGENT_SERVICE_UNAVAILABLE" }, 503),
  );

  app.get("/health/live", (context) => context.json({ status: "ok" }));
  app.get("/health/ready", async (context) => {
    try {
      const ready = await (dependencies.readiness?.() ?? Promise.resolve(true));
      return context.json(
        { status: ready ? "ready" : "unavailable" },
        ready ? 200 : 503,
      );
    } catch {
      return context.json({ status: "unavailable" }, 503);
    }
  });

  app.use("/api/agent/*", async (context, next) => {
    context.header("Cache-Control", "no-store");
    context.header("Vary", "Origin, Sec-Fetch-Site");
    if (!isSameOriginBrowserRequest(context.req.raw.headers, dependencies.publicOrigin)) {
      return context.json({ code: "ORIGIN_NOT_ALLOWED" }, 403);
    }

    let researcher: VerifiedResearcher | null;
    try {
      researcher = await dependencies.verifySession(context.req.raw.headers);
    } catch (error) {
      if (error instanceof AgentAuthenticationUnavailableError) {
        return context.json({ code: "AUTH_SERVICE_UNAVAILABLE" }, 503);
      }
      throw error;
    }
    if (researcher === null) {
      return context.json({ code: "AUTHENTICATION_REQUIRED" }, 401);
    }
    context.set("researcher", researcher);
    await next();
  });

  app.get("/api/agent/models", (context) => {
    return context.json(dependencies.modelCatalog);
  });

  app.get("/api/agent/sessions", async (context) => {
    try {
      const page = await dependencies.sessions(
        readSessionCursor(context.req.raw),
        context.get("researcher"),
      );
      return context.json({
        next_cursor: page.nextCursor,
        sessions: page.sessions.map(sessionResponse),
      });
    } catch (error) {
      return sessionErrorResponse(context, error);
    }
  });

  app.get("/api/agent/sessions/:threadId", async (context) => {
    const threadId = context.req.param("threadId");
    if (!isChatThreadId(threadId)) {
      return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
    }
    try {
      return context.json(sessionResponse(await dependencies.session(
        threadId,
        context.get("researcher"),
      )));
    } catch (error) {
      return sessionErrorResponse(context, error);
    }
  });

  app.patch(
    "/api/agent/sessions/:threadId",
    bodyLimit({
      maxSize: MAX_SESSION_RENAME_BODY_BYTES,
      onError: (context) => context.json({ code: "INVALID_CHAT_SESSION_REQUEST" }, 400),
    }),
    async (context) => {
      const threadId = context.req.param("threadId");
      if (!isChatThreadId(threadId)) {
        return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
      }
      try {
        const input = await readRenameSessionInput(context.req.raw);
        const session = await dependencies.renameSession(
          threadId,
          context.get("researcher"),
          input.title,
          input.expectedVersion,
        );
        return context.json({
          id: session.id,
          title: session.title,
          version: session.version,
        });
      } catch (error) {
        return sessionErrorResponse(context, error);
      }
    },
  );

  app.delete("/api/agent/sessions/:threadId", async (context) => {
    const threadId = context.req.param("threadId");
    if (!isChatThreadId(threadId) || new URL(context.req.url).search.length > 0) {
      return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
    }
    try {
      await dependencies.deleteSession(threadId, context.get("researcher"));
      return context.body(null, 204);
    } catch (error) {
      return sessionErrorResponse(context, error);
    }
  });

  app.get("/api/agent/sessions/:threadId/preferences", async (context) => {
    const preference = await dependencies.sessionPreference(
      context.req.param("threadId"),
      context.get("researcher"),
    );
    if (preference === null) {
      return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
    }
    return context.json(preference);
  });

  app.all("/api/agent/copilotkit/*", (context) => {
    return dependencies.handleRuntime(
      context.req.raw,
      context.get("researcher"),
    );
  });

  return app;
}

function sessionResponse(session: SessionPage["sessions"][number]) {
  return {
    active_run: session.activeRun,
    activity_at: session.activityAt,
    created_at: session.createdAt,
    id: session.id,
    title: session.title,
    version: session.version,
  };
}

function sessionErrorResponse(
  context: Parameters<Parameters<Hono<AgentAppEnvironment>["onError"]>[0]>[1],
  error: unknown,
): Response {
  if (error instanceof SessionInputError) {
    return context.json({ code: "INVALID_CHAT_SESSION_REQUEST" }, 400);
  }
  if (error instanceof SessionNotFoundError) {
    return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
  }
  if (error instanceof SessionVersionConflictError) {
    return context.json({ code: "CHAT_SESSION_CHANGED" }, 409);
  }
  if (error instanceof SessionActiveRunError) {
    return context.json({ code: "CHAT_SESSION_RUN_ACTIVE" }, 409);
  }
  throw error;
}

function isSameOriginBrowserRequest(headers: Headers, publicOrigin: string): boolean {
  const origin = headers.get("origin");
  if (origin !== null) return origin === publicOrigin;
  return headers.get("sec-fetch-site") === "same-origin";
}
