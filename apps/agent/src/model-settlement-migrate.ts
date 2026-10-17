import { runAgentMigration } from "./migration-command.js";
import { migrateModelSettlement } from "./model-settlement-migration.js";
runAgentMigration(
  migrateModelSettlement,
  "0001-model-settlement-receipt.json",
).catch(() => {
  process.stderr.write(
    JSON.stringify({ code: "AGENT_MODEL_SETTLEMENT_MIGRATION_FAILED" }) + "\n",
  );
  process.exitCode = 1;
});
