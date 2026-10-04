import { createHash } from "node:crypto";
import { readFile, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { parseArgs } from "node:util";
import { Pool } from "pg";
import { migrateUnifiedRefreshProofs } from "./unified-refresh-migration.js";

async function main() {
  const { values } = parseArgs({ options: { apply: { type: "boolean", default: false }, "backup-directory": { type: "string" } } });
  const backup = values["backup-directory"];
  if (!backup) throw new Error("--backup-directory is required");
  const dump = join(backup, "database.dump");
  if (values.apply && !(await stat(dump)).size) throw new Error("Save a PostgreSQL backup before --apply");
  const connectionString = process.env.THESISTRACE_OWNER_DATABASE_URL;
  if (!connectionString) throw new Error("THESISTRACE_OWNER_DATABASE_URL is required");
  const pool = new Pool({ connectionString });
  try {
    const report = await migrateUnifiedRefreshProofs(pool, values.apply);
    if (values.apply) {
      const digest = createHash("sha256").update(await readFile(dump)).digest("hex");
      const path = join(backup, "auth-0001-receipt.json");
      try { await writeFile(path, JSON.stringify({ ...report, databaseBackupSha256: digest }), { flag: "wx", mode: 0o600 }); }
      catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        const previous = JSON.parse(await readFile(path, "utf8"));
        if (previous.migration !== report.migration || previous.databaseBackupSha256 !== digest) throw new Error("Migration receipt does not match this backup");
      }
    }
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } finally { await pool.end(); }
}

main().catch(error => { process.stderr.write(`${String(error)}\n`); process.exitCode = 1; });
