import { serve } from "@hono/node-server";

import { createAgentApp } from "./app.js";
import { readAgentSettings } from "./config.js";
import { createSessionVerifier } from "./session-verifier.js";

async function main(): Promise<void> {
  const settings = readAgentSettings();
  const app = createAgentApp({
    modelCatalog: settings.modelRegistry.safeCatalog,
    publicOrigin: settings.publicOrigin,
    verifySession: createSessionVerifier({
      authInternalOrigin: settings.authInternalOrigin,
    }),
  });
  const server = serve({
    fetch: app.fetch,
    hostname: settings.host,
    port: settings.port,
  });

  let closing = false;
  const close = () => {
    if (closing) return;
    closing = true;
    server.close(() => {
      process.exitCode = 0;
    });
  };
  process.once("SIGINT", close);
  process.once("SIGTERM", close);
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
