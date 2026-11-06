import type { Page } from "@playwright/test";
import { expect, sameOriginHeaders, test } from "./auth-fixture";
import { revealToolActivity, submitChatPrompt, waitForChatTurn } from "../fixtures/chat-ui";

test("Code Mode combines authenticated reads and replays their safe activities", async ({ page }) => {
  await page.goto("/chat");
  await completedPrompt(page, "[scripted-code-mode] Compare authenticated research reads.");
  await expect(page.getByText("Compared 2 authenticated reads in one program.", { exact: true })).toBeVisible();
  await expect(await revealToolActivity(page, "execute_typescript", "complete")).toHaveCount(1);
  await expect(await revealToolActivity(page, "get_research_context", "complete")).toHaveCount(1);
  await expect(await revealToolActivity(page, "get_alpha_catalog", "complete")).toHaveCount(1);
  await expect(page.locator("body")).not.toContainText("private-code-mode-console-canary");
  await page.reload();
  await expect(await revealToolActivity(page, "execute_typescript", "complete")).toHaveCount(1);
  await expect(await revealToolActivity(page, "get_research_context", "complete")).toHaveCount(1);
  await expect(await revealToolActivity(page, "get_alpha_catalog", "complete")).toHaveCount(1);
});

test("Code Mode synchronous execution keeps another Chat responsive and stops durably", async ({ page, context }) => {
  test.setTimeout(45_000);
  await page.goto("/chat");
  const turnId = await submitChatPrompt(page, "[scripted-code-mode-stop] Keep this program running until Stop.");
  await revealToolActivity(page, "get_research_context", "complete");
  const models = await page.request.get("/api/agent/models", { headers: sameOriginHeaders(), timeout: 3_000 });
  expect(models.ok()).toBe(true);
  const other = await context.newPage();
  try {
    await other.goto("/chat");
    await completedPrompt(other, "Explain a testable Alpha idea.");
    await expect(other.locator("[data-chat-status]")).toHaveText("Run complete");
  } finally { await other.close(); }
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await waitForChatTurn(page, turnId, "stopped");
  await expect(await revealToolActivity(page, "get_research_context", "complete")).toHaveCount(1);
  await page.reload();
  await waitForChatTurn(page, turnId, "stopped");
  await expect(await revealToolActivity(page, "get_research_context", "complete")).toHaveCount(1);
  await completedPrompt(page, "[scripted-code-mode] Compare after Stop.");
  await expect(page.getByText("Compared 2 authenticated reads in one program.", { exact: true })).toBeVisible();
  await expect(page.getByText("Turn stopped", { exact: true })).toBeVisible();
});

test("Code Mode analysis preserves direct Research submission and authoritative cards", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto("/chat");
  await completedPrompt(page, "Evaluate a low-volatility Alpha idea as a Factor Evaluation using reliable ThesisTrace defaults.");
  await revealToolActivity(page, "execute_typescript", "complete");
  await revealToolActivity(page, "diagnose_alpha_formula", "complete");
  await revealToolActivity(page, "submit_research_run", "complete");
  const response = await page.request.get("/api/research-runs");
  expect(response.ok()).toBe(true);
  const list = await response.json();
  expect(list.items).toHaveLength(1);
  const run = await factorRun(page, list.items[0].id);
  expect(run.status).toBe("succeeded");
  expect(run.input.research_kind).toBe("factor_evaluation");
  await assertFactorCard(page, run);
  await page.reload();
  await assertFactorCard(page, run);
  await testInfo.attach("code-mode-direct-research-desktop", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});

test("Code Mode compares real child Results and restores their cards", async ({ page }, testInfo) => {
  test.setTimeout(150_000);
  await page.goto("/chat");
  await completedPrompt(page, "Compare positive and negative price-rank Alpha signals as Factor Evaluations.");
  await revealToolActivity(page, "submit_research_batch", "complete");
  const response = await page.request.get("/api/research-batches");
  expect(response.ok()).toBe(true);
  const list = await response.json();
  expect(list.items).toHaveLength(1);
  const id = list.items[0].id as string;
  expect(id).toMatch(/^batch_[a-f0-9]{20}$/);
  await expect.poll(async () => (await (await page.request.get(`/api/research-batches/${id}`)).json()).status,
    { timeout: 60_000 }).toBe("succeeded");
  const batch = await (await page.request.get(`/api/research-batches/${id}`)).json();
  expect(batch.items).toHaveLength(2);
  await completedPrompt(page, "Resume the Research Batch from this Chat and explain each authoritative Child Result.");
  await revealToolActivity(page, "get_research_run_result", "complete");
  const runs = await Promise.all(batch.items.map((item: { research_run_id: string }) => factorRun(page, item.research_run_id)));
  expect(runs.map((run: FactorRun) => run.input.formula)).toEqual(["rank(close)", "-rank(close)"]);
  for (const run of runs) await assertFactorCard(page, run);
  await page.reload();
  for (const run of runs) await assertFactorCard(page, run);
  await testInfo.attach("code-mode-comparison-desktop", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});

async function completedPrompt(page: Page, prompt: string) {
  await waitForChatTurn(page, await submitChatPrompt(page, prompt), "completed", 90_000);
}

type FactorRun = {
  id: string; name: string; status: string;
  input: { formula: string; research_kind: string };
  result: { factor: { horizons: Record<string, { summary: { rank_ic: { mean: number | null } } }> } };
};
async function factorRun(page: Page, id: string): Promise<FactorRun> {
  expect(id).toMatch(/^run_[a-f0-9]{20}$/);
  const response = await page.request.get(`/api/research-runs/${id}`);
  expect(response.ok()).toBe(true);
  return await response.json();
}

async function assertFactorCard(page: Page, run: FactorRun) {
  const card = page.getByRole("article", { name: "Research surface" }).last()
    .getByRole("region", { name: `ResearchRun ${run.id}`, exact: true });
  await expect(card.getByRole("link", { name: run.name, exact: true })).toHaveAttribute("href", `/research-runs/${run.id}`);
  await expect(card).toContainText(run.input.formula);
  for (const horizon of ["1", "5", "20"]) {
    const value = run.result.factor.horizons[horizon]!.summary.rank_ic.mean;
    await expect(card.getByText(`${horizon}S Rank IC`, { exact: true }).locator(".."))
      .toContainText(value === null ? "—" : value.toFixed(3));
  }
}
