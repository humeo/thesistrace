import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";

import { expect, sameOriginHeaders, test, testProjectName } from "./auth-fixture";
import { revealToolActivity, submitChatPrompt } from "./chat-ui";
import { proxyState, setProxyMode } from "./fault-proxy";
import { controlWorker } from "./research-run-control";

const factorPrompt = "Compare positive and negative price-rank Alpha signals as Factor Evaluations.";
const strategyPrompt = "Compare focused and broad holdings for a price-rank Alpha strategy.";
const resumePrompt = "Resume the Research Batch from this Chat and explain each authoritative Child Result.";

for (const mode of ["factor_evaluation", "strategy_sweep"] as const) {
test(`Chat Batch ${mode} preserves ordered child Results independently of its Session`, async ({ page, researcher }, testInfo) => {
  test.setTimeout(240_000);
  const browserCoreWrites: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET" && /^\/api\/(research-runs|research-batches|daily-tracks)/.test(path)) {
      browserCoreWrites.push(`${request.method()} ${path}`);
    }
  });
  await page.goto("/chat");
  let paused = false;
  if (mode === "factor_evaluation") {
    controlWorker("pause", "batch-research-worker");
    paused = true;
  }
  let originalSurface = "";
  let batchId = "";
  try {
    await send(page, mode === "factor_evaluation" ? factorPrompt : strategyPrompt);
    await expect((await revealToolActivity(page, "submit_research_batch", "complete")).last()).toBeVisible();
    const surface = page.getByRole("article", { name: "Research surface" }).first();
    await expect(surface).toBeVisible();
    originalSurface = await surface.innerText();
    const match = originalSurface.match(/batch_[a-f0-9]{20}/);
    if (match === null) throw new Error("Batch surface exposed no authoritative Batch identity");
    batchId = match[0];
    if (paused) {
      expect(originalSurface).toContain("queued");
      expect(originalSurface).toContain("0/2 completed");
      controlWorker("unpause", "batch-research-worker");
      paused = false;
    }
    await expect.poll(async () => (await batch(page, batchId)).status, { timeout: 90_000 }).toBe("succeeded");
  } finally {
    if (paused) controlWorker("unpause", "batch-research-worker");
  }
  const complete = await batch(page, batchId);
  expect(complete.batch_kind).toBe(mode);
  expect(complete.items.map((item) => item.ordinal)).toEqual([1, 2]);
  expect(complete.items.map((item) => item.item_key)).toEqual(mode === "factor_evaluation"
    ? ["positive-price-rank", "negative-price-rank"] : ["focused-holdings", "broad-holdings"]);
  expect(new Set(complete.items.map((item) => item.research_run_id)).size).toBe(2);
  await send(page, resumePrompt);
  await expect(page.getByRole("article", { name: "Research surface" }).first()).toHaveText(originalSurface, { useInnerText: true });
  const comparison = page.getByRole("table", { name: "Ordered child ResearchRun results" }).last();
  await expect(comparison).toBeVisible();
  await expect(comparison.getByRole("row")).toHaveCount(3);
  const childSnapshots = new Map<string, ChildRun>();
  for (const [ordinal, item] of complete.items.entries()) {
    const run = await childRun(page, item.research_run_id);
    childSnapshots.set(item.research_run_id, run);
    expect(run).toMatchObject({
      id: item.research_run_id,
      status: "succeeded",
      input: { research_kind: mode === "factor_evaluation" ? "factor_evaluation" : "strategy_backtest", universe: "top1000", neutralization: "none" },
      result: { provenance: { research_run_id: item.research_run_id } },
    });
    const row = comparison.getByRole("row").nth(ordinal + 1);
    await expect(row).toContainText(item.item_key);
    await expect(row).toContainText(item.research_run_id);
    if (mode === "factor_evaluation") {
      expect(run.input.formula).toBe(ordinal === 0 ? "rank(close)" : "-rank(close)");
      const value = run.result.factor.horizons["5"].summary.rank_ic.mean;
      await expect(row).toContainText(value === null ? "Unavailable" : value.toFixed(4));
    } else {
      expect(run.input.holdings_count).toBe(ordinal === 0 ? 10 : 20);
      expect(run.input.rebalance_every_sessions).toBe(5);
      const value = run.result.strategy?.summary.metrics.sharpe;
      expect(value).not.toBeUndefined();
      await expect(row).toContainText(value === null ? "Unavailable" : value!.toFixed(4));
    }
    await expect(page.getByRole("link", { name: `Open ${item.item_key} ResearchRun`, exact: true }).last()).toHaveAttribute("href", `/research-runs/${item.research_run_id}`);
  }
  expect(batchDatabaseFacts(researcher.id)).toMatchObject({
    admissions: 1, batches: 1, children: 2, generations: 1, folder_ids: ["folder_batch_research"],
    request_ids: [expect.stringMatching(/^agent_[a-f0-9]{32}_batch_v1$/)],
  });
  await expect(page.getByRole("button", { name: /^(Cancel|Confirm|Stop)( Batch)?$/ })).toHaveCount(0);
  const transcript = page.getByRole("log", { name: "Conversation timeline", exact: true });
  await expect(transcript).not.toContainText(/manifest|checkpoint|object_key|lease_owner/);
  expect(browserCoreWrites).toEqual([]);
  const durableUrl = page.url();
  const sessionId = new URL(durableUrl).searchParams.get("session");
  if (sessionId === null) throw new Error("Batch Chat has no durable Session");
  const resultText = await comparison.innerText();
  await page.reload();
  await expect(page.getByRole("table", { name: "Ordered child ResearchRun results" }).last()).toHaveText(resultText, { useInnerText: true });
  expect(batchDatabaseFacts(researcher.id)).toMatchObject({ admissions: 1, batches: 1, children: 2 });
  await testInfo.attach(`${mode}-desktop`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  await page.setViewportSize({ width: 390, height: 844 });
  const narrowTable = page.getByRole("table", { name: "Ordered child ResearchRun results" }).last();
  await expect(narrowTable.getByRole("columnheader")).toHaveText(["Order", "Item", "ResearchRun", "Status", "Result"]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await testInfo.attach(`${mode}-mobile`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  await page.setViewportSize({ width: 1280, height: 900 });

  const currentTitle = (await page.locator(".chat-session-title strong").innerText()).trim();
  await page.getByRole("button", { name: `Actions for ${currentTitle}` }).click();
  await page.getByRole("menuitem", { name: "Rename", exact: true }).click();
  const rename = page.getByRole("dialog", { name: "Rename Chat" });
  const renamedTitle = `Independent ${mode} comparison`;
  await rename.getByLabel("Title").fill(renamedTitle);
  await rename.getByRole("button", { name: "Save title" }).click();
  await expect(rename).toHaveCount(0);
  expect(await batch(page, batchId)).toEqual(complete);
  await send(page, "List my recent Research Batches.");
  await expect((await revealToolActivity(page, "list_research_batches", "complete")).last()).toBeVisible();
  expect(batchDatabaseFacts(researcher.id)).toMatchObject({ admissions: 1, batches: 1 });
  const navigation = page.getByRole("link", { name: `Open ${complete.items[0]!.item_key} ResearchRun`, exact: true }).last();
  await navigation.click();
  await expect(page).toHaveURL(new RegExp(`/research-runs/${complete.items[0]!.research_run_id}$`));
  await expect(page.getByRole("heading", { name: mode === "factor_evaluation" ? "Factor Summary" : "Strategy Summary" })).toBeVisible();
  await page.goto(durableUrl);
  await page.getByRole("button", { name: `Actions for ${renamedTitle}` }).click();
  await page.getByRole("menuitem", { name: "Delete Chat" }).click();
  await page.getByRole("dialog", { name: "Delete Chat?" }).getByRole("button", { name: "Delete Chat" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  expect((await page.request.get(`/api/agent/sessions/${sessionId}`, { headers: sameOriginHeaders() })).status()).toBe(404);
  expect(await batch(page, batchId)).toEqual(complete);
  for (const [runId, snapshot] of childSnapshots) expect(await childRun(page, runId)).toEqual(snapshot);
  expect(batchDatabaseFacts(researcher.id)).toMatchObject({ admissions: 1, batches: 1, children: 2, generations: 1 });
});
}

test("Chat Batch response loss replays the same admission and child identities", async ({ page, researcher }) => {
  test.setTimeout(240_000);
  await page.goto("/chat");
  setProxyMode("mcp-fault-proxy", 8150, "tool-call", "disconnect-submit");
  try {
    await page.getByRole("textbox", { name: "Message", exact: true }).fill(factorPrompt);
    await page.getByRole("button", { name: "Send" }).click();
    await expect(runStatus(page)).toHaveText("Run failed", { timeout: 30_000 });
    await expect((await revealToolActivity(page, "submit_research_batch", "failed")).last()).toBeVisible();
    expect(Number(proxyState("mcp-fault-proxy", 8150).disconnected_submit_responses)).toBeGreaterThanOrEqual(1);
    const before = batchDatabaseFacts(researcher.id);
    expect(before).toMatchObject({ admissions: 1, batches: 1, children: 2 });
    const batchId = before.batch_ids[0];
    if (batchId === undefined) throw new Error("Lost response created no Batch receipt");
    await expect.poll(async () => (await batch(page, batchId)).status, { timeout: 90_000 }).toBe("succeeded");
    const beforeReplay = await batch(page, batchId);
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await send(page, resumePrompt);
    await expect((await revealToolActivity(page, "submit_research_batch", "complete")).last()).toBeVisible();
    await expect(page.getByRole("table", { name: "Ordered child ResearchRun results" })).toBeVisible();
    expect(batchDatabaseFacts(researcher.id)).toEqual(before);
    expect(await batch(page, batchId)).toEqual(beforeReplay);
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
  }
});

function runStatus(page: Page) { return page.locator("[data-chat-status]"); }

async function send(page: Page, prompt: string): Promise<void> {
  await submitChatPrompt(page, prompt);
  await expect(runStatus(page)).toHaveText("Run complete", { timeout: 90_000 });
}

type Batch = Readonly<{
  id: string; batch_kind: string; status: string;
  items: ReadonlyArray<{ ordinal: number; item_key: string; research_run_id: string; status: string }>;
}>;
async function batch(page: Page, id: string): Promise<Batch> {
  const response = await page.request.get(`/api/research-batches/${id}`);
  expect(response.status()).toBe(200);
  return await response.json() as Batch;
}

type ChildRun = Readonly<{
  id: string; status: string;
  input: { formula: string; holdings_count?: number; rebalance_every_sessions?: number };
  result: {
    factor: { horizons: Record<string, { summary: { rank_ic: { mean: number | null } } }> };
    strategy?: { summary: { metrics: { sharpe: number | null } } };
  };
}>;
async function childRun(page: Page, id: string): Promise<ChildRun> {
  const response = await page.request.get(`/api/research-runs/${id}`);
  expect(response.status()).toBe(200);
  return await response.json() as ChildRun;
}

type BatchFacts = Readonly<{
  admissions: number; batches: number; children: number; generations: number;
  batch_ids: readonly string[]; folder_ids: readonly string[]; request_ids: readonly string[];
}>;
function batchDatabaseFacts(researcherId: string): BatchFacts {
  if (!/^[0-9a-f-]{36}$/.test(researcherId)) throw new Error("Batch inspection requires a safe Researcher ID");
  const output = execFileSync("docker", [
    "exec", "--env", "PGPASSWORD=owner-test-password", `${testProjectName()}-postgres-1`,
    "psql", "--username", "thesistrace_owner", "--dbname", "thesistrace", "--tuples-only", "--no-align", "--set", "ON_ERROR_STOP=1", "--command", `
      SELECT json_build_object(
        'admissions', (SELECT count(*) FROM research_batches.admission_receipts WHERE researcher_id = '${researcherId}'::uuid),
        'batches', (SELECT count(*) FROM research_batches.batches WHERE researcher_id = '${researcherId}'::uuid),
        'batch_ids', (SELECT json_agg(id ORDER BY id) FROM research_batches.batches WHERE researcher_id = '${researcherId}'::uuid),
        'request_ids', (SELECT json_agg(request_id ORDER BY request_id) FROM research_batches.admission_receipts WHERE researcher_id = '${researcherId}'::uuid),
        'children', count(*),
        'generations', count(DISTINCT immutable_input->'data_admission'->>'generation_manifest_sha256'),
        'folder_ids', json_agg(DISTINCT folder_id)
      ) FROM research_runs.runs WHERE researcher_id = '${researcherId}'::uuid;
    `,
  ], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 10_000 });
  return JSON.parse(output) as BatchFacts;
}
