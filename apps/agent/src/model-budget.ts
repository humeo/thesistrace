import { randomUUID } from "node:crypto";
import { z } from "zod";
import type { Pool } from "pg";
import type { LanguageModelV3Usage } from "@ai-sdk/provider";
import type { RegisteredModel } from "./model-registry.js";
import { AgentRunFailure } from "./run-failure.js";

const limit = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER).nullable();
const policySchema = z.object({
  timezone: z.string().refine(value => {
    try { new Intl.DateTimeFormat("en", { timeZone: value }); return true; }
    catch { return false; }
  }),
  daily_model_budget_nanodollars: limit,
  daily_run_limit: limit,
  active_daily_track_limit: limit,
}).strict();
export type ModelReservation = Readonly<{ id: string; amount: number }>;

export class ModelBudget {
  constructor(private readonly pool: Pool, private readonly authOrigin: string,
    private readonly policyFetch: typeof fetch = globalThis.fetch) {}

  async reserve(researcherId: string, amount: number): Promise<ModelReservation> {
    exactAmount(amount);
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [`model-budget:${researcherId}`]);
      const policy = await this.policy(researcherId);
      const day = await client.query<{ day: string }>("SELECT (clock_timestamp() AT TIME ZONE $1)::date::text AS day", [policy.timezone]);
      const date = day.rows[0]!.day;
      const result = await client.query<{ used: string }>(`
        SELECT COALESCE(sum(COALESCE(actual_nanodollars, reserved_nanodollars)), 0)::text AS used
        FROM agent.model_charge WHERE researcher_id = $1 AND budget_day = $2
      `, [researcherId, date]);
      if (policy.daily_model_budget_nanodollars !== null
        && BigInt(result.rows[0]!.used) + BigInt(amount) > BigInt(policy.daily_model_budget_nanodollars)) {
        throw new AgentRunFailure("DAILY_MODEL_BUDGET_EXCEEDED");
      }
      const id = randomUUID();
      await client.query(`INSERT INTO agent.model_charge
        (id, researcher_id, budget_day, reserved_nanodollars) VALUES ($1, $2, $3, $4)`,
      [id, researcherId, date, amount]);
      await client.query("COMMIT");
      return { id, amount };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally { client.release(); }
  }

  async settle(reservation: ModelReservation, amount: number): Promise<void> {
    exactAmount(amount);
    const result = await this.pool.query(`UPDATE agent.model_charge SET actual_nanodollars = $2
      WHERE id = $1 AND (actual_nanodollars IS NULL OR actual_nanodollars = $2) RETURNING id`,
    [reservation.id, amount]);
    if (result.rowCount !== 1) throw new Error("MODEL_CHARGE_SETTLEMENT_CONFLICT");
  }

  private async policy(researcherId: string): Promise<z.infer<typeof policySchema>> {
    try {
      const response = await this.policyFetch(`${this.authOrigin}/internal/researchers/${researcherId}/quota-policy`,
        { redirect: "error", signal: AbortSignal.timeout(2000) });
      if (!response.ok) throw new AgentRunFailure("AGENT_UNAVAILABLE");
      return policySchema.parse(await response.json());
    } catch { throw new AgentRunFailure("AGENT_UNAVAILABLE"); }
  }
}

export function modelCost(usage: LanguageModelV3Usage, pricing: RegisteredModel["pricing"]): number | null {
  const input = usage?.inputTokens?.total, output = usage?.outputTokens?.total;
  const read = pricing.cacheRead === pricing.input ? 0 : usage?.inputTokens?.cacheRead;
  const write = pricing.cacheWrite === pricing.input ? 0 : usage?.inputTokens?.cacheWrite;
  if (![input, output, read, write].every(value => typeof value === "number" && Number.isSafeInteger(value) && value >= 0)) return null;
  if (read! + write! > input!) return null;
  const amount = (input! - read! - write!) * pricing.input + read! * pricing.cacheRead
    + write! * pricing.cacheWrite + output! * pricing.output;
  exactAmount(amount);
  return amount;
}

function exactAmount(amount: number): void {
  if (!Number.isSafeInteger(amount) || amount < 0) throw new Error("INVALID_MODEL_COST");
}
