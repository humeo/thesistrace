import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
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
  response.end(
    JSON.stringify({
      timezone: "Asia/Shanghai",
      daily_model_budget_nanodollars: unlimited ? null : dailyBudget,
      daily_run_limit: unlimited ? null : 10,
      active_daily_track_limit: unlimited ? null : 10,
    }),
  );
});
let budget: ModelBudget;
beforeAll(async () => {
  await pool.query("DROP SCHEMA IF EXISTS agent CASCADE");
  await initializeAgentSchema(pool);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No listener");
  budget = new ModelBudget(
    pool,
    `http://127.0.0.1:${address.port}`,
    undefined,
    ":memory:",
  );
});
beforeEach(async () => {
  dailyBudget = 1_000_000_000;
  await pool.query("DELETE FROM agent.model_charge");
});
afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
  await budget.close();
  await pool.end();
});
it("admits calls with positive remaining usage and records concurrent overshoot without reservations", async () => {
  const researcher = randomUUID();
  const first = await budget.begin(researcher);
  await budget.settle(first, 999_000_000);
  const calls = await Promise.all([budget.begin(researcher), budget.begin(researcher)]);
  expect(await budget.usage(researcher)).toMatchObject({
    actual_nanodollars: 999_000_000, reserved_nanodollars: 0, remaining_nanodollars: 1_000_000,
  });
  await Promise.all(calls.map(call => budget.settle(call, 10_000_000)));
  expect(await budget.usage(researcher)).toMatchObject({
    actual_nanodollars: 1_019_000_000, reserved_nanodollars: 0, remaining_nanodollars: 0,
  });
  await expect(budget.begin(researcher)).rejects.toMatchObject({ code: "DAILY_MODEL_BUDGET_EXCEEDED" });
});
it("keeps database connections available while waiting for the quota policy", async () => {
  const limitedPool = new Pool({
    connectionString: url,
    max: 1,
    connectionTimeoutMillis: 2_000,
  });
  let markEntered!: () => void;
  let releasePolicy!: () => void;
  const entered = new Promise<void>((resolve) => {
    markEntered = resolve;
  });
  const released = new Promise<void>((resolve) => {
    releasePolicy = resolve;
  });
  const delayed = new ModelBudget(
    limitedPool,
    "http://auth.invalid",
    async () => {
      markEntered();
      await released;
      return Response.json({
        timezone: "Asia/Shanghai",
        daily_model_budget_nanodollars: null,
        daily_run_limit: null,
        active_daily_track_limit: null,
      });
    },
    ":memory:",
  );
  const pending = delayed.begin(randomUUID());
  // Attach a handler before any asynchronous assertion can fail.
  const settled = Promise.allSettled([pending]);
  try {
    await entered;
    const query = await limitedPool.query("SELECT 1 AS available");
    expect(query.rows).toEqual([{ available: 1 }]);
  } finally {
    releasePolicy();
    await settled;
    await delayed.close();
    await limitedPool.end();
  }
  await expect(pending).resolves.toMatchObject({ id: expect.any(String) });
});
it("settles once and refuses the next call at the exact allowance", async () => {
  const researcher = randomUUID();
  const call = await budget.begin(researcher);
  await budget.settle(call, 200_000_000);
  await budget.settle(call, 200_000_000);
  await expect(budget.settle(call, 0)).rejects.toThrow("MODEL_CHARGE_SETTLEMENT_CONFLICT");
  const next = await budget.begin(researcher);
  await budget.settle(next, 800_000_000);
  await expect(budget.begin(researcher)).rejects.toMatchObject({ code: "DAILY_MODEL_BUDGET_EXCEEDED" });
});
it("exempts the current Operator and isolates researchers and Beijing dates", async () => {
  const operatorCall = await budget.begin(operator);
  await budget.settle(operatorCall, 2_000_000_000);
  await expect(budget.begin(operator)).resolves.toBeDefined();
  const researcher = randomUUID();
  const prior = await budget.begin(researcher);
  await budget.settle(prior, 1_000_000_000);
  await pool.query("UPDATE agent.model_charge SET budget_day = budget_day - 1 WHERE id = $1", [prior.id]);
  await expect(budget.begin(researcher)).resolves.toBeDefined();
  await expect(budget.begin(randomUUID())).resolves.toBeDefined();
  const result = await pool.query("SELECT count(*)::int AS count FROM agent.model_charge WHERE budget_day = (now() AT TIME ZONE 'Asia/Shanghai')::date");
  expect(result.rows[0].count).toBe(4);
});
it("uses changed policy values immediately and rejects zero allowance", async () => {
  const researcher = randomUUID();
  dailyBudget = 0;
  await expect(budget.begin(researcher)).rejects.toMatchObject({ code: "DAILY_MODEL_BUDGET_EXCEEDED" });
  dailyBudget = 200_000_000;
  const call = await budget.begin(researcher);
  await budget.settle(call, 200_000_000);
  await expect(budget.begin(researcher)).rejects.toMatchObject({ code: "DAILY_MODEL_BUDGET_EXCEEDED" });
  dailyBudget = 300_000_000;
  await expect(budget.begin(researcher)).resolves.toBeDefined();
});
it("fails closed when the quota policy is unavailable or malformed", async () => {
  for (const payload of [
    { unlimited: true },
    { timezone: "Asia/Shanghai" },
    {
      timezone: "invalid",
      daily_model_budget_nanodollars: 1,
      daily_run_limit: 1,
      active_daily_track_limit: 1,
    },
  ]) {
    const invalid = new ModelBudget(
      pool,
      "http://auth.invalid",
      async () => Response.json(payload),
      ":memory:",
    );
    await expect(invalid.begin(randomUUID())).rejects.toMatchObject({
      code: "AGENT_UNAVAILABLE",
    });
    await invalid.close();
  }
  const unavailable = new ModelBudget(
    pool,
    "http://auth.invalid",
    async () => {
      throw new Error("offline");
    },
    ":memory:",
  );
  await expect(unavailable.begin(randomUUID())).rejects.toMatchObject({
    code: "AGENT_UNAVAILABLE",
  });
  await unavailable.close();
  expect(
    (await pool.query("SELECT count(*)::int AS count FROM agent.model_charge"))
      .rows[0].count,
  ).toBe(0);
});

it("releases conclusively unknown finished calls without backcharging late usage", async () => {
  const researcher = randomUUID();
  const call = await budget.begin(researcher);
  await budget.absorb(call);
  await budget.settle(call, 200_000_000);
  await expect(
    budget.begin(researcher),
  ).resolves.toBeDefined();
});

it("durably recovers known usage before absorbing interrupted calls after a host restart", async () => {
  const directory = await mkdtemp(join(tmpdir(), "model-settlement-"));
  const journalPath = join(directory, "settlements.sqlite");
  const runtimeUrl = new URL(url!);
  runtimeUrl.username = "agent_runtime";
  runtimeUrl.password = "agent-test-password";
  const runtimePool = new Pool({ connectionString: runtimeUrl.href, max: 2 });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No listener");
  const origin = `http://127.0.0.1:${address.port}`;
  const interrupted = new ModelBudget(
    runtimePool,
    origin,
    undefined,
    journalPath,
  );
  let recovered: ModelBudget | undefined;
  const researcher = randomUUID();
  try {
    const known = await interrupted.begin(researcher);
    await interrupted.begin(researcher); // still executing when the host dies
    await pool.query("REVOKE UPDATE ON agent.model_charge FROM agent_runtime");
    await expect(
      interrupted.settle(known, 23_000_000),
    ).resolves.toBeUndefined();
    expect(
      (
        await pool.query(
          "SELECT actual_nanodollars FROM agent.model_charge WHERE id=$1",
          [known.id],
        )
      ).rows[0],
    ).toEqual({ actual_nanodollars: null });
    // A known cost waiting for durable database settlement must block admission,
    // even though no monetary reservation is held for the call.
    await expect(interrupted.begin(researcher)).rejects.toThrow();
    await interrupted.close();
    await pool.query("GRANT UPDATE ON agent.model_charge TO agent_runtime");
    recovered = new ModelBudget(runtimePool, origin, undefined, journalPath);
    await recovered.recoverInterrupted();
    expect(await recovered.usage(researcher)).toMatchObject({
      actual_nanodollars: 23_000_000,
      reserved_nanodollars: 0,
      remaining_nanodollars: 977_000_000,
    });
    expect(
      (
        await pool.query(
          "SELECT settlement_state,actual_nanodollars FROM agent.model_charge ORDER BY settlement_state DESC",
        )
      ).rows,
    ).toEqual([
      { settlement_state: "settled", actual_nanodollars: "23000000" },
      { settlement_state: "absorbed", actual_nanodollars: "0" },
    ]);
    await recovered.recoverInterrupted();
    await expect(
      recovered.begin(researcher),
    ).resolves.toBeDefined();
  } finally {
    await pool.query("GRANT UPDATE ON agent.model_charge TO agent_runtime");
    if (recovered) await recovered.close();
    await runtimePool.end();
    await rm(directory, { recursive: true, force: true });
  }
});
