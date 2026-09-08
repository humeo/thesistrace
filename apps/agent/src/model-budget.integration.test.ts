import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { Pool } from "pg";
import { afterAll, beforeAll, beforeEach, expect, it } from "vitest";
import { initializeAgentSchema } from "./schema-initialize.js";
import { ModelBudget } from "./model-budget.js";

const url = process.env.THESISTRACE_AGENT_TEST_OWNER_DATABASE_URL;
if (!url) throw new Error("Isolated database URL required");
const pool = new Pool({ connectionString: url, max: 6 });
const operator = randomUUID();
let dailyBudget = 1_000_000_000;
const server = createServer((request, response) => {
  response.setHeader("content-type", "application/json");
  const unlimited = request.url?.includes(operator) === true;
  response.end(JSON.stringify({ timezone: "Asia/Shanghai",
    daily_model_budget_nanodollars: unlimited ? null : dailyBudget,
    daily_run_limit: unlimited ? null : 10, active_daily_track_limit: unlimited ? null : 10 }));
});
let budget: ModelBudget;
beforeAll(async () => {
  await pool.query("DROP SCHEMA IF EXISTS agent CASCADE");
  await initializeAgentSchema(pool);
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No listener");
  budget = new ModelBudget(pool, `http://127.0.0.1:${address.port}`);
});
beforeEach(async () => { dailyBudget = 1_000_000_000; await pool.query("DELETE FROM agent.model_charge"); });
afterAll(async () => {
  await new Promise<void>(resolve => server.close(() => resolve()));
  await pool.end();
});
it("admits exactly one concurrent call when only one reservation fits", async () => {
  const researcher = randomUUID();
  await budget.reserve(researcher, 900_000_000);
  const outcomes = await Promise.allSettled([budget.reserve(researcher, 100_000_000), budget.reserve(researcher, 100_000_000)]);
  expect(outcomes.filter(result => result.status === "fulfilled")).toHaveLength(1);
  expect(outcomes.filter(result => result.status === "rejected")).toHaveLength(1);
});
it("settles once, releases the unused reservation, and retains unknown calls", async () => {
  const researcher = randomUUID();
  const call = await budget.reserve(researcher, 1_000_000_000);
  await expect(budget.reserve(researcher, 1)).rejects.toMatchObject({ code: "DAILY_MODEL_BUDGET_EXCEEDED" });
  await budget.settle(call, 200_000_000);
  await budget.settle(call, 200_000_000);
  await expect(budget.settle(call, 0)).rejects.toThrow("MODEL_CHARGE_SETTLEMENT_CONFLICT");
  await budget.reserve(researcher, 800_000_000);
  await expect(budget.reserve(researcher, 1)).rejects.toMatchObject({ code: "DAILY_MODEL_BUDGET_EXCEEDED" });
});
it("exempts the current Operator and isolates researchers and Beijing dates", async () => {
  await budget.reserve(operator, 2_000_000_000);
  const researcher = randomUUID();
  const prior = await budget.reserve(researcher, 1_000_000_000);
  await pool.query("UPDATE agent.model_charge SET budget_day = budget_day - 1 WHERE id = $1", [prior.id]);
  await expect(budget.reserve(researcher, 1_000_000_000)).resolves.toBeDefined();
  await expect(budget.reserve(randomUUID(), 1_000_000_000)).resolves.toBeDefined();
  const result = await pool.query("SELECT count(*)::int AS count FROM agent.model_charge WHERE budget_day = (now() AT TIME ZONE 'Asia/Shanghai')::date");
  expect(result.rows[0].count).toBe(3);
});

it("uses changed policy values immediately instead of a local dollar constant", async () => {
  const researcher = randomUUID();
  dailyBudget = 200_000_000;
  await budget.reserve(researcher, 200_000_000);
  await expect(budget.reserve(researcher, 1)).rejects.toMatchObject({ code: "DAILY_MODEL_BUDGET_EXCEEDED" });
  dailyBudget = 300_000_000;
  await expect(budget.reserve(researcher, 100_000_000)).resolves.toBeDefined();
});
it("fails closed when the quota policy is unavailable or malformed", async () => {
  for (const payload of [{ unlimited: true }, { timezone: "Asia/Shanghai" },
    { timezone: "invalid", daily_model_budget_nanodollars: 1, daily_run_limit: 1, active_daily_track_limit: 1 }]) {
    const invalid = new ModelBudget(pool, "http://auth.invalid", async () => Response.json(payload));
    await expect(invalid.reserve(randomUUID(), 0)).rejects.toMatchObject({ code: "AGENT_UNAVAILABLE" });
  }
  const unavailable = new ModelBudget(pool, "http://auth.invalid", async () => { throw new Error("offline"); });
  await expect(unavailable.reserve(randomUUID(), 0)).rejects.toMatchObject({ code: "AGENT_UNAVAILABLE" });
  expect((await pool.query("SELECT count(*)::int AS count FROM agent.model_charge")).rows[0].count).toBe(0);
});
