import { readAgentInitializerSettings } from "./config.js";
import { createAgentInitializerPool } from "./database.js";
import { diagnoseAgentFailure } from "./failure.js";
import { initializeAgentSchema } from "./schema-initialize.js";

async function main(): Promise<void> {
  const settings = readAgentInitializerSettings();
  const pool = createAgentInitializerPool(settings.databaseUrl);
  try {
    await initializeAgentSchema(pool);
  } finally {
    await pool.end();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`${JSON.stringify({
    code: "AGENT_SCHEMA_CONTRACT_INVALID",
    event: "agent_initialize_failed",
    ...diagnoseAgentFailure(error),
  })}\n`);
  process.exitCode = 1;
});
