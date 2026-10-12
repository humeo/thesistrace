import { runAuthMigration } from "./migration-command.js";
import { migrateRetiredInvitations } from "./retire-invitations-migration.js";

runAuthMigration(migrateRetiredInvitations, "auth-0002-receipt.json").catch(error => {
  process.stderr.write(`${String(error)}\n`); process.exitCode = 1;
});
