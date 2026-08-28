import { serve } from "@hono/node-server";

import { createAuthApp } from "./app.js";
import { createThesisTraceAuth } from "./auth.js";
import { readAuthSettings } from "./config.js";
import { createAuthPool } from "./database.js";
import { diagnoseAuthFailure } from "./failure.js";
import { checkAuthReadiness } from "./readiness.js";
import { verifyAuthSchema } from "./schema-contract.js";

async function main(): Promise<void> {
  const settings = readAuthSettings();
  const pool = createAuthPool(settings.databaseUrl);
  pool.on("error", (error) => {
    process.stderr.write(
      `${JSON.stringify({
        code: "AUTH_DATABASE_UNAVAILABLE",
        event: "auth_database_pool_error",
        ...diagnoseAuthFailure(error),
      })}\n`,
    );
  });

  try {
    await verifyAuthSchema(pool);
    const auth = createThesisTraceAuth(settings, pool);
    const app = createAuthApp({
      authHandler: (request) => auth.handler(request),
      getSession: (input) => auth.api.getSession(input),
      readiness: () => checkAuthReadiness(pool),
    });
    const server = serve({
      fetch: app.fetch,
      hostname: settings.host,
      port: settings.port,
    });

    let closing = false;
    const close = () => {
      if (closing) {
        return;
      }
      closing = true;
      server.close(() => {
        void pool.end().finally(() => {
          process.exitCode = 0;
        });
      });
    };
    process.once("SIGINT", close);
    process.once("SIGTERM", close);
  } catch (error) {
    await pool.end().catch(() => undefined);
    throw error;
  }
}

main().catch((error: unknown) => {
  process.stderr.write(
    `${JSON.stringify({
      code: "AUTH_STARTUP_INVALID",
      event: "auth_startup_failed",
      ...diagnoseAuthFailure(error),
    })}\n`,
  );
  process.exitCode = 1;
});
