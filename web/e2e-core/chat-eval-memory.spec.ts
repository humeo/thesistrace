import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import { expect, sameOriginHeaders, test, testProjectName } from "./auth-fixture";
import { controlWorker } from "./research-run-control";

test("Eval correction fixture produces a real warmup rejection and one accepted fixed-window Run", async ({ page }) => {
  test.setTimeout(90_000);
  const command = {
    request_id: "eval-warmup-original", folder_id: "folder_default", name: "Isolated warmup oracle",
    formula: "ts_mean(close, 2)", hypothesis: null, start_date: "2010-01-04", end_date: "2026-08-04",
    universe: "top300", neutralization: "none", research_kind: "factor_evaluation",
  };
  const rejected = await page.request.post("/api/research-runs", { data: command, headers: sameOriginHeaders() });
  expect(rejected.status()).toBe(422);
  expect(await rejected.json()).toMatchObject({ issues: [{ code: "INSUFFICIENT_CALCULATION_WARMUP", field: "start_date" }] });
  const before = await page.request.get("/api/research-runs");
  expect((await before.json()).items).toEqual([]);
  const accepted = await page.request.post("/api/research-runs", {
    data: { ...command, request_id: "eval-warmup-corrected", start_date: "2026-07-09" }, headers: sameOriginHeaders(),
  });
  expect(accepted.status()).toBe(202);
  const runId = (await accepted.json()).id;
  await expect.poll(async () => (await (await page.request.get(`/api/research-runs/${runId}`)).json()).status, { timeout: 60_000 }).toBe("succeeded");
  expect((await (await page.request.get("/api/research-runs")).json()).items).toHaveLength(1);
});

for (const kind of ["formula", "admission"] as const) {
  test(`Eval correction oracle reads real ${kind} Tool outcomes without exporting Memory`, async ({ page, researcher }, testInfo) => {
    test.setTimeout(120_000);
    const prompt = kind === "formula"
      ? "Develop a low-volatility Alpha, repair any Formula issue you discover, and evaluate it."
      : "Evaluate a low-volatility Alpha and correct one structured admission issue if needed.";
    await page.goto("/chat");
    await page.getByRole("textbox", { name: "Message", exact: true }).fill(prompt);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator("[data-chat-status]")).toHaveText("Run complete", { timeout: 90_000 });
    const threadId = new URL(page.url()).searchParams.get("session");
    expect(threadId).toMatch(/^[a-f0-9-]{36}$/);
    const list = await (await page.request.get("/api/research-runs")).json();
    expect(list.items).toHaveLength(1);
    const run = await (await page.request.get(`/api/research-runs/${list.items[0].id}`)).json();
    expect(run.status).toBe("succeeded");
    const expectedRun = Object.fromEntries(["formula", "start_date", "end_date", "universe", "neutralization", "research_kind"].map((key) => [key, run.input[key]]));
    expectedRun.id = run.id;
    const input = { thread_id: threadId, researcher_id: researcher.id,
      expectation: kind === "formula"
        ? { kind, original_formula: "rank(-abs(pct_change(clsoe, 1)))", run: expectedRun }
        : { kind, requested_start: "2010-01-04", run: expectedRun },
    };
    const facts = oracle(input);
    expect(facts).toEqual({ formula_corrected: kind === "formula", admission_corrected: kind === "admission", unresolved_admission_rejection: false, batch_results_inspected: false });
    expect(() => oracle({ ...input, researcher_id: randomUUID() })).toThrow("EVAL_MEMORY_ORACLE_UNAVAILABLE");
    await testInfo.attach("correction-engineering-evidence", { body: JSON.stringify({
      kind: "deterministic-engineering-evidence", model_quality_evidence: false, ...facts,
    }), contentType: "application/json" });
  });
}

test("Eval Memory oracle does not confuse completed Batch artifacts with inspecting both child Results", async ({ page, researcher }, testInfo) => {
  test.setTimeout(180_000);
  await page.goto("/chat");
  controlWorker("pause", "batch-research-worker");
  try {
    await page.getByRole("textbox", { name: "Message", exact: true }).fill("Compare positive and negative price-rank Alpha signals as Factor Evaluations.");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator("[data-chat-status]")).toHaveText("Run complete", { timeout: 60_000 });
  } finally { controlWorker("unpause", "batch-research-worker"); }
  const threadId = new URL(page.url()).searchParams.get("session");
  expect(threadId).toMatch(/^[a-f0-9-]{36}$/);
  const list = await (await page.request.get("/api/research-batches")).json();
  expect(list.items).toHaveLength(1);
  const batchPath = `/api/research-batches/${list.items[0].id}`;
  await expect.poll(async () => (await (await page.request.get(batchPath)).json()).status, { timeout: 60_000 }).toBe("succeeded");
  const batch = await (await page.request.get(batchPath)).json();
  expect(batch.items).toHaveLength(2);
  const runIds = batch.items.map((item: { research_run_id: string }) => item.research_run_id);
  for (const runId of runIds) {
    const run = await (await page.request.get(`/api/research-runs/${runId}`)).json();
    expect(run).toMatchObject({ id: runId, status: "succeeded", result: { provenance: { research_run_id: runId } } });
  }
  const input = { thread_id: threadId, researcher_id: researcher.id, expectation: { kind: "batch-results", run_ids: runIds } };
  expect(oracle(input)).toMatchObject({ batch_results_inspected: false });
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Resume the Research Batch from this Chat and explain each authoritative Child Result.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator("[data-chat-status]")).toHaveText("Run complete", { timeout: 60_000 });
  const facts = oracle(input);
  expect(facts).toEqual({ formula_corrected: false, admission_corrected: false, unresolved_admission_rejection: false, batch_results_inspected: true });
  expect(oracle({ ...input, expectation: { kind: "batch-results", run_ids: [runIds[0], "run_00000000000000000001"] } }))
    .toMatchObject({ batch_results_inspected: false });
  expect(() => oracle({ ...input, researcher_id: randomUUID() })).toThrow("EVAL_MEMORY_ORACLE_UNAVAILABLE");
  await testInfo.attach("batch-inspection-engineering-evidence", { body: JSON.stringify({
    kind: "deterministic-engineering-evidence", model_quality_evidence: false, ...facts,
  }), contentType: "application/json" });
});

function oracle(input: object): Record<string, boolean> {
  try {
    const output = execFileSync("docker", ["exec", "--interactive", "--env", "THESISTRACE_AGENT_EVAL_ORACLE=isolated", `${testProjectName()}-agent-1`,
      "node", "--input-type=module", "--eval", "import { runResearchEvalMemoryOracle } from './dist/research-eval-memory.js'; await runResearchEvalMemoryOracle();"],
    { input: JSON.stringify(input), encoding: "utf8", stdio: ["pipe", "pipe", "pipe"], timeout: 15_000 });
    return JSON.parse(output) as Record<string, boolean>;
  } catch { throw new Error("EVAL_MEMORY_ORACLE_UNAVAILABLE"); }
}
