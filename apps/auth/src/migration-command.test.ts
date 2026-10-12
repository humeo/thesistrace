import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runAuthMigration } from "./migration-command.js";

vi.mock("pg", () => ({ Pool: class { async end() {} } }));
let directory: string;
let applied: boolean;
const originalArgv = process.argv;
const migration = "fixture_explicit_upgrade";
const migrate = async (_pool: unknown, apply: boolean) => {
  if (apply) applied = true;
  return { migration, status: apply ? "applied" : "validated" };
};

describe("explicit Auth command backup boundary", () => {
  beforeEach(async () => {
    directory = await mkdtemp(join(tmpdir(), "thesistrace-migration-command-"));
    applied = false;
    process.argv = ["node", "migration", "--apply", "--backup-directory", directory];
    vi.stubEnv("THESISTRACE_OWNER_DATABASE_URL", "postgresql://fixture.invalid/db");
    vi.spyOn(process.stdout, "write").mockImplementation(() => true);
  });
  afterEach(async () => {
    process.argv = originalArgv;
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    await rm(directory, { recursive: true, force: true });
  });
  it("rejects a missing or empty backup without applying the upgrade", async () => {
    await expect(runAuthMigration(migrate, "receipt.json")).rejects.toThrow();
    expect(applied).toBe(false);
    await writeFile(join(directory, "database.dump"), "");
    await expect(runAuthMigration(migrate, "receipt.json")).rejects.toThrow("backup");
    expect(applied).toBe(false);
  });
  it("rejects a mismatched existing receipt before applying the upgrade", async () => {
    await writeFile(join(directory, "database.dump"), "fixture-snapshot");
    await writeFile(join(directory, "receipt.json"), JSON.stringify({migration, databaseBackupSha256: "different"}));
    await expect(runAuthMigration(migrate, "receipt.json")).rejects.toThrow("does not match");
    expect(applied).toBe(false);
  });
  it("records the backup digest and accepts a repeat using the same backup", async () => {
    await writeFile(join(directory, "database.dump"), "fixture-snapshot");
    await runAuthMigration(migrate, "receipt.json");
    expect(applied).toBe(true);
    const receipt = JSON.parse(await readFile(join(directory, "receipt.json"), "utf8"));
    expect(receipt).toEqual({migration, status: "applied", databaseBackupSha256: createHash("sha256").update("fixture-snapshot").digest("hex")});
    await runAuthMigration(migrate, "receipt.json");
    expect(JSON.parse(await readFile(join(directory, "receipt.json"), "utf8"))).toEqual(receipt);
  });
});
