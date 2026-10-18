import { runAuthMigration } from "./migration-command.js";
import { migrateZeroValuePeriods } from "./zero-value-periods-migration.js";
import { diagnoseAuthFailure } from "./failure.js";

runAuthMigration(migrateZeroValuePeriods, "0004-zero-value-periods-receipt.json").catch((error) => {
  process.stderr.write(JSON.stringify({ code: "AUTH_ZERO_VALUE_PERIODS_MIGRATION_FAILED", ...diagnoseAuthFailure(error) }) + "\n");
  process.exitCode = 1;
});
