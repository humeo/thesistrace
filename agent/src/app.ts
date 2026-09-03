import { Hono } from "hono";
import { bodyLimit } from "hono/body-limit";

import { AgentAuthenticationUnavailableError } from "./failure.js";
import { isChatThreadId } from "./chat-request.js";
import {
  ChatControlError,
  MAX_CHAT_COMMAND_BODY_BYTES,
  readSteerInput,
  readStopInput,
  readTimelineQuery,
  type CommandReceipt,
  type SteerInput,
  type StopInput,
  type TimelineCursor,
  type TimelinePage,
} from "./chat-control.js";
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
  commandReceipt: (
    threadId: string,
    commandId: string,
    researcher: VerifiedResearcher,
  ) => Promise<CommandReceipt>;
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
  steer: (
    threadId: string,
    researcher: VerifiedResearcher,
    input: SteerInput,
  ) => Promise<CommandReceipt>;
  stop: (
    threadId: string,
    researcher: VerifiedResearcher,
    input: StopInput,
  ) => Promise<CommandReceipt>;
  timeline: (
    threadId: string,
    researcher: VerifiedResearcher,
    before: TimelineCursor | undefined,
    limit: number,
  ) => Promise<TimelinePage>;
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
    const threadId = context.req.param("threadId");
    if (!isChatThreadId(threadId)) {
      return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
    }
    try {
      const preference = await dependencies.sessionPreference(
        threadId,
        context.get("researcher"),
      );
      if (preference === null) {
        return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
      }
      return context.json(preference);
    } catch (error) {
      return sessionErrorResponse(context, error);
    }
  });

  app.get("/api/agent/sessions/:threadId/timeline", async (context) => {
    const threadId = context.req.param("threadId");
    if (!isChatThreadId(threadId)) {
      return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
    }
    try {
      const query = readTimelineQuery(context.req.raw);
      const page = await dependencies.timeline(
        threadId,
        context.get("researcher"),
        query.before,
        query.limit,
      );
      return context.json({
        next_cursor: page.nextCursor,
        turns: page.turns.map((turn) => ({
          completed_at: turn.completedAt,
          entries: turn.entries.map((entry) => ({
            created_at: entry.createdAt,
            entry_id: entry.entryId,
            kind: entry.kind,
            payload: timelinePayloadResponse(entry),
            turn_id: entry.turnId,
          })),
          id: turn.id,
          started_at: turn.startedAt,
          status: turn.status,
        })),
      });
    } catch (error) {
      return sessionErrorResponse(context, error);
    }
  });

  app.get("/api/agent/sessions/:threadId/commands/:commandId", async (context) => {
    const threadId = context.req.param("threadId");
    const commandId = context.req.param("commandId");
    if (!isChatThreadId(threadId) || !isChatThreadId(commandId)) {
      return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
    }
    try {
      return context.json(commandResponse(await dependencies.commandReceipt(
        threadId,
        commandId,
        context.get("researcher"),
      )));
    } catch (error) {
      return sessionErrorResponse(context, error);
    }
  });

  app.post(
    "/api/agent/sessions/:threadId/steer",
    bodyLimit({
      maxSize: MAX_CHAT_COMMAND_BODY_BYTES,
      onError: (context) => context.json({ code: "INVALID_CHAT_INPUT" }, 400),
    }),
    async (context) => {
      const threadId = context.req.param("threadId");
      if (!isChatThreadId(threadId)) {
        return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
      }
      try {
        const receipt = await dependencies.steer(
          threadId,
          context.get("researcher"),
          await readSteerInput(context.req.raw),
        );
        return context.json(commandResponse(receipt), receipt.status === "pending" ? 202 : 200);
      } catch (error) {
        return sessionErrorResponse(context, error);
      }
    },
  );

  app.post(
    "/api/agent/sessions/:threadId/stop",
    bodyLimit({
      maxSize: MAX_CHAT_COMMAND_BODY_BYTES,
      onError: (context) => context.json({ code: "INVALID_CHAT_INPUT" }, 400),
    }),
    async (context) => {
      const threadId = context.req.param("threadId");
      if (!isChatThreadId(threadId)) {
        return context.json({ code: "CHAT_SESSION_NOT_FOUND" }, 404);
      }
      try {
        const receipt = await dependencies.stop(
          threadId,
          context.get("researcher"),
          await readStopInput(context.req.raw),
        );
        return context.json(commandResponse(receipt), receipt.status === "pending" ? 202 : 200);
      } catch (error) {
        return sessionErrorResponse(context, error);
      }
    },
  );

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
    activity_at: session.activityAt,
    created_at: session.createdAt,
    current_turn: turnResponse(session.currentTurn),
    id: session.id,
    latest_turn: turnResponse(session.latestTurn),
    title: session.title,
    version: session.version,
  };
}

function turnResponse(turn: SessionPage["sessions"][number]["latestTurn"]) {
  return turn === null ? null : {
    id: turn.id,
    kind: turn.kind,
    model_key: turn.modelKey,
    question: turn.question === null ? null : {
      interrupt_id: turn.question.interruptId,
      options: turn.question.options,
      question: turn.question.question,
      selection_mode: turn.question.selectionMode,
    },
    reasoning_effort: turn.reasoningEffort,
    started_at: turn.startedAt,
    status: turn.status,
    terminal_error_code: turn.terminalErrorCode,
  };
}

function commandResponse(receipt: CommandReceipt) {
  return {
    command_id: receipt.commandId,
    error_code: receipt.errorCode,
    kind: receipt.kind,
    status: receipt.status,
    turn_id: receipt.turnId,
  };
}

function timelinePayloadResponse(entry: TimelinePage["turns"][number]["entries"][number]) {
  if (entry.kind !== "question") return entry.payload;
  return {
    interrupt_id: entry.payload.interruptId,
    options: entry.payload.options,
    question: entry.payload.question,
    selection_mode: entry.payload.selectionMode,
    status: entry.payload.status,
  };
}

function sessionErrorResponse(
  context: Parameters<Parameters<Hono<AgentAppEnvironment>["onError"]>[0]>[1],
  error: unknown,
): Response {
  if (error instanceof SessionInputError) {
    return context.json({ code: "INVALID_CHAT_SESSION_REQUEST" }, 400);
  }
  if (error instanceof ChatControlError) {
    return context.json({ code: error.code }, error.status);
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
  // Every dependency behind the product Session surface is storage-backed.
  // Runtime/provider availability uses the separate CopilotKit boundary and
  // keeps AGENT_SERVICE_UNAVAILABLE, so clients can recover appropriately.
  return context.json({ code: "CHAT_STORAGE_FAILURE" }, 503);
}

function isSameOriginBrowserRequest(headers: Headers, publicOrigin: string): boolean {
  const origin = headers.get("origin");
  if (origin !== null) return origin === publicOrigin;
  return headers.get("sec-fetch-site") === "same-origin";
}
