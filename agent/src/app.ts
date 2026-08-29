import { Hono } from "hono";

import { AgentAuthenticationUnavailableError } from "./failure.js";
import type { SafeModelCatalog } from "./model-registry.js";
import type { VerifiedResearcher } from "./session-verifier.js";

export type AgentAppDependencies = Readonly<{
  modelCatalog: SafeModelCatalog;
  publicOrigin: string;
  readiness?: () => Promise<boolean>;
  verifySession: (headers: Headers) => Promise<VerifiedResearcher | null>;
}>;

export function createAgentApp(dependencies: AgentAppDependencies): Hono {
  const app = new Hono();
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

  app.get("/api/agent/models", async (context) => {
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
    return context.json(dependencies.modelCatalog);
  });

  return app;
}

function isSameOriginBrowserRequest(headers: Headers, publicOrigin: string): boolean {
  const origin = headers.get("origin");
  if (origin !== null) return origin === publicOrigin;
  return headers.get("sec-fetch-site") === "same-origin";
}
