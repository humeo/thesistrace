import { runAuthMigration } from "./migration-command.js";
import { migrateBilling } from "./billing-migration.js";
import { diagnoseAuthFailure } from "./failure.js";

runAuthMigration(migrateBilling, "0003-billing-receipt.json").catch((error) => {
  process.stderr.write(
    JSON.stringify({
      code: "AUTH_BILLING_MIGRATION_FAILED",
      ...diagnoseAuthFailure(error),
    }) + "\n",
  );
  process.exitCode = 1;
});
