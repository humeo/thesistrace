import { Hono } from "hono";

import { AgentAuthenticationUnavailableError } from "./failure.js";
import type { SafeModelCatalog } from "./model-registry.js";
import type { VerifiedResearcher } from "./session-verifier.js";

export type AgentAppDependencies = Readonly<{
  handleRuntime: (
    request: Request,
    researcher: VerifiedResearcher,
  ) => Promise<Response>;
  modelCatalog: SafeModelCatalog;
  publicOrigin: string;
  readiness?: () => Promise<boolean>;
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

function isSameOriginBrowserRequest(headers: Headers, publicOrigin: string): boolean {
  const origin = headers.get("origin");
  if (origin !== null) return origin === publicOrigin;
  return headers.get("sec-fetch-site") === "same-origin";
}
