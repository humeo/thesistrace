import { serve } from "@hono/node-server";
import { createServer, type Server } from "node:http";
import { asyncExitHook } from "exit-hook";

import { createMcpRunFactory } from "./mcp-run.js";
import { checkMcpConnection } from "./mcp-connection.js";
import { createAgentApp } from "./app.js";
import { readAgentSettings } from "./config.js";
import { createResearchRuntime } from "./research-runtime.js";
import { createSessionVerifier } from "./session-verifier.js";

async function main(): Promise<void> {
  const settings = readAgentSettings();
  const researchRuntime = await createResearchRuntime(settings);
  const mcpFactory = createMcpRunFactory(settings);
  const app = createAgentApp({
    mcpConnection: (headers) => checkMcpConnection(mcpFactory, headers),
    commandReceipt: researchRuntime.commandReceipt,
    deleteSession: researchRuntime.deleteSession,
    handleRuntime: researchRuntime.handle,
    modelCatalog: settings.modelRegistry.safeCatalog,
    publicOrigin: settings.publicOrigin,
    readiness: researchRuntime.ready,
    renameSession: researchRuntime.renameSession,
    session: researchRuntime.session,
    sessionPreference: researchRuntime.preference,
    sessions: researchRuntime.sessions,
    steer: researchRuntime.steer,
    stop: researchRuntime.stop,
    timeline: researchRuntime.timeline,
    verifySession: createSessionVerifier({
      authInternalOrigin: settings.authInternalOrigin,
    }),
  });
  const server = serve({
    createServer,
    fetch: app.fetch,
    hostname: settings.host,
    port: settings.port,
  }) as Server;

  // Mastra MCP uses exit-hook to terminate on signals. Join its awaited
  // lifecycle instead of racing it with a separate process signal listener.
  asyncExitHook(async () => {
    // Stop unfinished framework Runs before waiting for their SSE connections
    // to close. Waiting for HTTP first leaves shutdown blocked on the model.
    try {
      await Promise.all([
        new Promise<void>((resolve, reject) => {
          server.close((error) => error === undefined ? resolve() : reject(error));
        }),
        researchRuntime.close().finally(() => {
          // CopilotKit/Caddy can retain a streaming HTTP reader after its Run
          // has terminated. No new requests are accepted, and all model/Memory
          // work is drained before detaching the remaining sockets.
          server.closeAllConnections();
        }),
      ]);
      process.stdout.write(`${JSON.stringify({ event: "agent_shutdown_completed" })}\n`);
    } catch {
      process.stderr.write(`${JSON.stringify({ event: "agent_shutdown_failed" })}\n`);
    }
  }, { wait: 10_000 });
}

main().catch(() => {
  process.stderr.write(
    `${JSON.stringify({
      code: "AGENT_STARTUP_INVALID",
      event: "agent_startup_failed",
    })}\n`,
  );
  process.exitCode = 1;
});
