import { expect, it } from "vitest";
import { createAgentPool, createAgentReadinessPool } from "./database.js";

const url = process.env.THESISTRACE_AGENT_TEST_OWNER_DATABASE_URL;
if (!url) throw new Error("Isolated database URL required");

it("waits for admitted work behind busy runtime connections while readiness remains independent", async () => {
  const runtime = createAgentPool(url);
  const readiness = createAgentReadinessPool(url);
  const clients = await Promise.all(Array.from({ length: 10 }, () => runtime.connect()));
  // Controlled database latency reproduces queued work exceeding the health budget.
  const busy = Promise.allSettled(clients.map(async client => {
    try { await client.query("SELECT pg_sleep(2.2)"); }
    finally { client.release(); }
  }));
  const queued = Promise.allSettled(Array.from({ length: 50 }, () => runtime.query("SELECT 1 AS available")));
  try {
    expect((await readiness.query("SELECT 1 AS available")).rows).toEqual([{ available: 1 }]);
    const results = await queued;
    expect((await busy).every(result => result.status === "fulfilled")).toBe(true);
    expect(results.every(result => result.status === "fulfilled"
      && result.value.rows[0]?.available === 1)).toBe(true);
  } finally {
    await busy;
    await queued;
    await Promise.all([runtime.end(), readiness.end()]);
  }
}, 15_000);
