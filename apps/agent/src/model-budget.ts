import { randomUUID } from "node:crypto";
import { z } from "zod";
import type { Pool } from "pg";
import type { LanguageModelV3Usage } from "@ai-sdk/provider";
import type { RegisteredModel } from "./model-registry.js";
import { ModelSettlementJournal } from "./model-settlement-journal.js";
import { AgentRunFailure } from "./run-failure.js";

const limit = z
  .number()
  .int()
  .nonnegative()
  .max(Number.MAX_SAFE_INTEGER)
  .nullable();
const policySchema = z
  .object({
    timezone: z.string().refine((value) => {
      try {
        new Intl.DateTimeFormat("en", { timeZone: value });
        return true;
      } catch {
        return false;
      }
    }),
    daily_model_budget_nanodollars: limit,
    daily_run_limit: limit,
    active_daily_track_limit: limit,
  })
  .strict();
export type ModelCall = Readonly<{ id: string }>;

export type ModelUsage = {
  actual_nanodollars: number;
  reserved_nanodollars: number;
  remaining_nanodollars: number | null;
  limit_nanodollars: number | null;
  resets_at: string;
  timezone: string;
};

export class ModelBudget {
  private readonly journal: ModelSettlementJournal;
  private flushing: Promise<void> | undefined;
  constructor(
    private readonly pool: Pool,
    private readonly authOrigin: string,
    private readonly policyFetch: typeof fetch = globalThis.fetch,
    journalPath: string,
  ) {
    this.journal = new ModelSettlementJournal(journalPath);
  }

  async begin(
    researcherId: string,
    runId?: string,
  ): Promise<ModelCall> {
    // Apply known pending costs before admitting another provider call.
    await this.reconcile();
    // Remote policy lookup must not hold a pooled connection or the budget lock.
    const policy = await this.policy(researcherId);
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        [`model-budget:${researcherId}`],
      );
      const day = await client.query<{ day: string }>(
        "SELECT (clock_timestamp() AT TIME ZONE $1)::date::text AS day",
        [policy.timezone],
      );
      const date = day.rows[0]!.day;
      const result = await client.query<{ used: string }>(
        `
        SELECT COALESCE(sum(actual_nanodollars), 0)::text AS used
        FROM agent.model_charge WHERE researcher_id = $1 AND budget_day = $2
      `,
        [researcherId, date],
      );
      if (
        policy.daily_model_budget_nanodollars !== null &&
        BigInt(result.rows[0]!.used) >=
          BigInt(policy.daily_model_budget_nanodollars)
      ) {
        throw new AgentRunFailure("DAILY_MODEL_BUDGET_EXCEEDED");
      }
      const id = randomUUID();
      // Keep a durable in-flight call for settlement/recovery, without holding
      // money. Concurrent calls may finish beyond the daily allowance.
      await client.query(
        `INSERT INTO agent.model_charge
        (id, researcher_id, budget_day, reserved_nanodollars,run_id) VALUES ($1, $2, $3, 0,$4)`,
        [id, researcherId, date, runId ?? null],
      );
      await client.query("COMMIT");
      return { id };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async settle(call: ModelCall, amount: number): Promise<void> {
    exactAmount(amount);
    this.journal.record({ id: call.id, kind: "settled", amount });
    await this.flushOrDefer();
  }
  async absorb(call: ModelCall): Promise<void> {
    this.journal.record({ id: call.id, kind: "absorbed", amount: 0 });
    await this.flushOrDefer();
  }
  /** On this single Agent host, all calls from the prior host have ended.
   * Replay known costs first; only then absorb truly unknown interrupted calls. */
  async recoverInterrupted(): Promise<void> {
    await this.reconcile();
    const charges = await this.pool.query<{ id: string }>(
      "SELECT id FROM agent.model_charge WHERE settlement_state='reserved' ORDER BY id",
    );
    for (const charge of charges.rows)
      this.journal.record({ id: charge.id, kind: "absorbed", amount: 0 });
    await this.reconcile();
  }
  reconcile(): Promise<void> {
    if (!this.flushing)
      this.flushing = this.flush().finally(() => {
        this.flushing = undefined;
      });
    return this.flushing;
  }
  private async flush(): Promise<void> {
    for (;;) {
      const pending = this.journal.pending();
      if (!pending.length) return;
      for (const value of pending) {
        const result =
          value.kind === "absorbed"
            ? await this.pool.query(
                `UPDATE agent.model_charge SET
              actual_nanodollars=CASE WHEN settlement_state='reserved' THEN 0 ELSE actual_nanodollars END,
              settlement_state=CASE WHEN settlement_state='reserved' THEN 'absorbed' ELSE settlement_state END,
              finished_at=COALESCE(finished_at,now()) WHERE id=$1 RETURNING id`,
                [value.id],
              )
            : await this.pool.query(
                `UPDATE agent.model_charge SET actual_nanodollars=CASE WHEN settlement_state='absorbed' THEN 0 ELSE $2 END,
              settlement_state=CASE WHEN settlement_state='absorbed' THEN 'absorbed' ELSE 'settled' END,finished_at=COALESCE(finished_at,now())
              WHERE id=$1 AND (settlement_state='absorbed' OR actual_nanodollars IS NULL OR actual_nanodollars=$2) RETURNING id`,
                [value.id, value.amount],
              );
        if (result.rowCount !== 1) {
          // A definitive conflict cannot overwrite the existing immutable cost.
          this.journal.remove(value.id);
          throw new Error("MODEL_CHARGE_SETTLEMENT_CONFLICT");
        }
        this.journal.remove(value.id);
      }
    }
  }
  private async flushOrDefer(): Promise<void> {
    try {
      await this.reconcile();
    } catch (error) {
      if (
        error instanceof Error &&
        error.message === "MODEL_CHARGE_SETTLEMENT_CONFLICT"
      )
        throw error;
      process.stderr.write(
        JSON.stringify({
          event: "model_settlement_deferred",
          code: "DATABASE_WRITE_UNAVAILABLE",
        }) + "\n",
      );
    }
  }
  async close(): Promise<void> {
    try {
      await this.flushOrDefer();
    } finally {
      this.journal.close();
    }
  }

  async usage(researcherId: string) {
    await this.reconcile();
    const policy = await this.policy(researcherId);
    const row = (
      await this.pool.query<{
        actual: string;
        reserved: string;
        resets_at: Date;
      }>(
        `
      SELECT COALESCE(sum(actual_nanodollars),0)::text actual,
        COALESCE(sum(CASE WHEN settlement_state='reserved' THEN reserved_nanodollars ELSE 0 END),0)::text reserved,
        (date_trunc('day',now() AT TIME ZONE $2)+interval '1 day') AT TIME ZONE $2 resets_at
      FROM agent.model_charge WHERE researcher_id=$1 AND budget_day=(now() AT TIME ZONE $2)::date`,
        [researcherId, policy.timezone],
      )
    ).rows[0]!;
    const actual = Number(row.actual),
      reserved = Number(row.reserved),
      limit = policy.daily_model_budget_nanodollars;
    if (!Number.isSafeInteger(actual) || !Number.isSafeInteger(reserved))
      throw new Error("MODEL_USAGE_OVERFLOW");
    return {
      actual_nanodollars: actual,
      reserved_nanodollars: reserved,
      remaining_nanodollars:
        limit === null ? null : Math.max(0, limit - actual - reserved),
      limit_nanodollars: limit,
      resets_at: row.resets_at.toISOString(),
      timezone: policy.timezone,
    };
  }

  private async policy(
    researcherId: string,
  ): Promise<z.infer<typeof policySchema>> {
    try {
      const response = await this.policyFetch(
        `${this.authOrigin}/internal/researchers/${researcherId}/quota-policy`,
        { redirect: "error", signal: AbortSignal.timeout(2000) },
      );
      if (!response.ok) throw new AgentRunFailure("AGENT_UNAVAILABLE");
      return policySchema.parse(await response.json());
    } catch {
      throw new AgentRunFailure("AGENT_UNAVAILABLE");
    }
  }
}

export function modelCost(
  usage: LanguageModelV3Usage,
  pricing: RegisteredModel["pricing"],
): number | null {
  const input = usage?.inputTokens?.total,
    output = usage?.outputTokens?.total;
  const read =
    pricing.cacheRead === pricing.input ? 0 : usage?.inputTokens?.cacheRead;
  const write =
    pricing.cacheWrite === pricing.input ? 0 : usage?.inputTokens?.cacheWrite;
  if (
    ![input, output, read, write].every(
      (value) =>
        typeof value === "number" && Number.isSafeInteger(value) && value >= 0,
    )
  )
    return null;
  if (read! + write! > input!) return null;
  const amount =
    (input! - read! - write!) * pricing.input +
    read! * pricing.cacheRead +
    write! * pricing.cacheWrite +
    output! * pricing.output;
  exactAmount(amount);
  return amount;
}

function exactAmount(amount: number): void {
  if (!Number.isSafeInteger(amount) || amount < 0)
    throw new Error("INVALID_MODEL_COST");
}
