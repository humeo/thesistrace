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
it("admits exactly one concurrent call when only one reservation fits", async () => {
  const researcher = randomUUID();
  await budget.reserve(researcher, 900_000_000);
  const outcomes = await Promise.allSettled([
    budget.reserve(researcher, 100_000_000),
    budget.reserve(researcher, 100_000_000),
  ]);
  expect(
    outcomes.filter((result) => result.status === "fulfilled"),
  ).toHaveLength(1);
  expect(
    outcomes.filter((result) => result.status === "rejected"),
  ).toHaveLength(1);
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
  const pending = delayed.reserve(randomUUID(), 0);
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
  await expect(pending).resolves.toMatchObject({ amount: 0 });
});
it("settles once, releases the unused reservation, and retains unknown calls", async () => {
  const researcher = randomUUID();
  const call = await budget.reserve(researcher, 1_000_000_000);
  await expect(budget.reserve(researcher, 1)).rejects.toMatchObject({
    code: "DAILY_MODEL_BUDGET_EXCEEDED",
  });
  await budget.settle(call, 200_000_000);
  await budget.settle(call, 200_000_000);
  await expect(budget.settle(call, 0)).rejects.toThrow(
    "MODEL_CHARGE_SETTLEMENT_CONFLICT",
  );
  await budget.reserve(researcher, 800_000_000);
  await expect(budget.reserve(researcher, 1)).rejects.toMatchObject({
    code: "DAILY_MODEL_BUDGET_EXCEEDED",
  });
});
it("exempts the current Operator and isolates researchers and Beijing dates", async () => {
  await budget.reserve(operator, 2_000_000_000);
  const researcher = randomUUID();
  const prior = await budget.reserve(researcher, 1_000_000_000);
  await pool.query(
    "UPDATE agent.model_charge SET budget_day = budget_day - 1 WHERE id = $1",
    [prior.id],
  );
  await expect(
    budget.reserve(researcher, 1_000_000_000),
  ).resolves.toBeDefined();
  await expect(
    budget.reserve(randomUUID(), 1_000_000_000),
  ).resolves.toBeDefined();
  const result = await pool.query(
    "SELECT count(*)::int AS count FROM agent.model_charge WHERE budget_day = (now() AT TIME ZONE 'Asia/Shanghai')::date",
  );
  expect(result.rows[0].count).toBe(3);
});

it("uses changed policy values immediately instead of a local dollar constant", async () => {
  const researcher = randomUUID();
  dailyBudget = 200_000_000;
  await budget.reserve(researcher, 200_000_000);
  await expect(budget.reserve(researcher, 1)).rejects.toMatchObject({
    code: "DAILY_MODEL_BUDGET_EXCEEDED",
  });
  dailyBudget = 300_000_000;
  await expect(budget.reserve(researcher, 100_000_000)).resolves.toBeDefined();
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
    await expect(invalid.reserve(randomUUID(), 0)).rejects.toMatchObject({
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
  await expect(unavailable.reserve(randomUUID(), 0)).rejects.toMatchObject({
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
  const call = await budget.reserve(researcher, 1_000_000_000);
  await budget.absorb(call);
  await budget.settle(call, 200_000_000);
  await expect(
    budget.reserve(researcher, 1_000_000_000),
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
    const known = await interrupted.reserve(researcher, 900_000_000);
    await interrupted.reserve(researcher, 100_000_000); // still executing when the host dies
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
          "SELECT settlement_state,actual_nanodollars FROM agent.model_charge ORDER BY reserved_nanodollars DESC",
        )
      ).rows,
    ).toEqual([
      { settlement_state: "settled", actual_nanodollars: "23000000" },
      { settlement_state: "absorbed", actual_nanodollars: "0" },
    ]);
    await recovered.recoverInterrupted();
    await expect(
      recovered.reserve(researcher, 977_000_000),
    ).resolves.toBeDefined();
  } finally {
    await pool.query("GRANT UPDATE ON agent.model_charge TO agent_runtime");
    if (recovered) await recovered.close();
    await runtimePool.end();
    await rm(directory, { recursive: true, force: true });
  }
});
