import { chmodSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { createRequire } from "node:module";
import type { DatabaseSync } from "node:sqlite";

export type ModelSettlement = Readonly<{
  id: string;
  kind: "settled" | "absorbed";
  amount: number;
}>;

/** A durable local outbox, not a second quota ledger. No model content is stored. */
export class ModelSettlementJournal {
  private readonly database: DatabaseSync;
  constructor(path: string) {
    if (path !== ":memory:")
      mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
    // Importing pricing/configuration helpers must not initialize SQLite or
    // change the machine-readable stderr contract of non-runtime CLIs.
    const sqlite = createRequire(import.meta.url)(
      "node:sqlite",
    ) as typeof import("node:sqlite");
    this.database = new sqlite.DatabaseSync(path);
    if (path !== ":memory:") chmodSync(path, 0o600);
    this.database.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL");
    const version = this.database.prepare("PRAGMA user_version").get()!
      .user_version;
    if (version === 0) {
      const tables = this.database
        .prepare("SELECT name FROM sqlite_schema WHERE type='table'")
        .all();
      if (tables.length) throw new Error("MODEL_SETTLEMENT_JOURNAL_INVALID");
      this.database.exec(`BEGIN;
        CREATE TABLE model_settlement(id TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('settled','absorbed')),
          amount INTEGER NOT NULL CHECK(amount>=0 AND (kind='settled' OR amount=0))) STRICT;
        PRAGMA user_version=1; COMMIT`);
    } else if (version !== 1)
      throw new Error("MODEL_SETTLEMENT_JOURNAL_INVALID");
    // Reject a corrupt or foreign journal rather than silently replacing it.
    if (this.database.prepare("PRAGMA quick_check").get()!.quick_check !== "ok")
      throw new Error("MODEL_SETTLEMENT_JOURNAL_INVALID");
    this.pending();
  }
  record(value: ModelSettlement): void {
    const existing = this.database
      .prepare("SELECT id,kind,amount FROM model_settlement WHERE id=?")
      .get(value.id);
    if (existing) {
      if (
        existing.kind === "settled" &&
        value.kind === "settled" &&
        existing.amount !== value.amount
      )
        throw new Error("MODEL_CHARGE_SETTLEMENT_CONFLICT");
      return;
    }
    this.database
      .prepare("INSERT INTO model_settlement(id,kind,amount) VALUES(?,?,?)")
      .run(value.id, value.kind, value.amount);
  }
  pending(): ModelSettlement[] {
    return this.database
      .prepare("SELECT id,kind,amount FROM model_settlement ORDER BY id")
      .all()
      .map((row) => {
        if (
          typeof row.id !== "string" ||
          (row.kind !== "settled" && row.kind !== "absorbed") ||
          typeof row.amount !== "number" ||
          !Number.isSafeInteger(row.amount) ||
          row.amount < 0
        )
          throw new Error("MODEL_SETTLEMENT_JOURNAL_INVALID");
        return { id: row.id, kind: row.kind, amount: row.amount };
      });
  }
  remove(id: string): void {
    this.database.prepare("DELETE FROM model_settlement WHERE id=?").run(id);
  }
  close(): void {
    this.database.close();
  }
}
