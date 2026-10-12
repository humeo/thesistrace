import { runAuthMigration } from "./migration-command.js";
import { migrateUnifiedRefreshProofs } from "./unified-refresh-migration.js";

runAuthMigration(migrateUnifiedRefreshProofs, "auth-0001-receipt.json").catch(error => {
  process.stderr.write(`${String(error)}\n`); process.exitCode = 1;
});
