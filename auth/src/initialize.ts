import { readAuthInitializerSettings } from "./config.js";
import { createAuthInitializerPool } from "./database.js";
import { diagnoseAuthFailure } from "./failure.js";
import { initializeAuthSchema } from "./schema-initialize.js";

async function main(): Promise<void> {
  const settings = readAuthInitializerSettings();
  const pool = createAuthInitializerPool(settings.databaseUrl);
  try {
    await initializeAuthSchema(pool);
  } finally {
    await pool.end();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(
    `${JSON.stringify({
      code: "AUTH_SCHEMA_CONTRACT_INVALID",
      event: "auth_initialize_failed",
      ...diagnoseAuthFailure(error),
    })}\n`,
  );
  process.exitCode = 1;
});
