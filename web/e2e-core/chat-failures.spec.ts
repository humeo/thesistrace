import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { expect, test, testProjectName } from "./auth-fixture";
import { modelPickerTrigger, revealToolActivity, selectModel, selectReasoning, submitChatPrompt } from "./chat-ui";
import { proxyState } from "./fault-proxy";
import { controlWorker } from "./research-run-control";

// Browser acceptance exercises the deployed Scripted Provider's public text
// seam; the web image must not import or ship the private Agent implementation.
const SCRIPTED_FAILURE_PROMPTS = {
  PROVIDER_TIMEOUT: "[scripted-provider-timeout] Test a bounded provider timeout.",
  PROVIDER_RATE_LIMIT: "[scripted-provider-rate-limit] Test provider rate limiting.",
  PROVIDER_AUTHENTICATION: "[scripted-provider-authentication] Test a rejected provider credential.",
  PROVIDER_REFUSAL: "[scripted-provider-refusal] Test a provider refusal.",
  PROVIDER_MALFORMED_STREAM: "[scripted-provider-malformed] Test an invalid provider stream.",
  OUTPUT_LIMIT: "[scripted-provider-output-limit] Test a bounded provider output.",
  INTERNAL_FAILURE: "[scripted-provider-unexpected] Test an unexpected provider error.",
} as const;
const SCRIPTED_FAILURE_AFTER_ADMISSION_PROMPT = "[scripted-failure-after-admission] Submit a low-volatility Factor Evaluation, then test provider failure.";
const SCRIPTED_RESUME_RESEARCH_PROMPT = "Resume the accepted ResearchRun from this Chat and explain its authoritative Result when available.";

for (const [code, prompt] of Object.entries(SCRIPTED_FAILURE_PROMPTS)) {
  test(`Chat bounded failure ${code} retains identity and requires explicit recovery`, async ({ page, researcher }, testInfo) => {
    if (code === "PROVIDER_TIMEOUT") await page.setViewportSize({ width: 390, height: 844 });
    const requests = observeRuns(page);
    const started = performance.now();
    await page.goto("/chat");
    await send(page, prompt);
    const error = page.locator(`.chat-turn-outcome-failed[data-failure-code="${code}"]`);
    await expect(error).toBeVisible();
    await expect(status(page)).toHaveText("Run failed");
    if (code === "PROVIDER_TIMEOUT") {
      const actionSize = await page.getByRole("button", { name: "Send", exact: true }).boundingBox();
      expect(actionSize?.width).toBeGreaterThanOrEqual(44);
      expect(actionSize?.height).toBeGreaterThanOrEqual(44);
      await testInfo.attach("mobile-bounded-failure", { contentType: "image/png", body: await page.screenshot() });
    }
    const runId = await page.locator(".chat-main").getAttribute("data-agent-run-id");
    await expect(page.locator(".chat-message-user")).toHaveCount(1);
    expect(requests).toHaveLength(1);
    expect(databaseFacts(researcher.id)).toMatchObject({ agent_runs: 1, user_messages: 1, active_runs: 0 });

    await page.reload();
    await expect(error).toBeVisible();
    await expect(page.locator(".chat-main")).toHaveAttribute("data-agent-run-id", runId!);
    await expect(page.locator(".chat-message-user")).toHaveCount(1);
    expect(requests).toHaveLength(1);
    await selectModel(page, "Scripted Deep Research");
    await selectReasoning(page, "High");
    await expect(modelPickerTrigger(page)).toHaveAccessibleName("Model Scripted Deep Research, reasoning High");
    expect(requests).toHaveLength(1);
    await send(page, "Continue with a testable Alpha idea.");
    await expect(status(page)).toHaveText("Run complete");
    await expect(error).toHaveCount(1);
    await expect(page.locator(".chat-message-user")).toHaveCount(2);
    await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();
    expect(requests).toHaveLength(2);
    expect(new Set(requests.map((request) => request.run_id)).size).toBe(2);
    expect(new Set(requests.map((request) => request.message_id)).size).toBe(2);
    expect(requests.map((request) => [request.model_key, request.reasoning])).toEqual([["scripted-research", "medium"], ["scripted-deep-research", "high"]]);
    const facts = databaseFacts(researcher.id);
    expect(facts).toMatchObject({ agent_runs: 2, user_messages: 2, active_runs: 0 });
    expect(facts.models[0]).toMatchObject({ model_key: "scripted-research", reasoning: "medium", status: "failed", code });
    expect(facts.models[1]).toMatchObject({ model_key: "scripted-deep-research", reasoning: "high", status: "completed", code: null });
    await testInfo.attach("bounded-failure-metadata", { contentType: "application/json", body: Buffer.from(JSON.stringify({
      category: code, dependency_status: "scripted-provider-fault-then-recovered", duration_ms: Math.round(performance.now() - started),
      facts, requests, seed: 0, expected_failed_model_steps: 1, test_trace_id: testInfo.testId, exit_code: 0,
    })) });
  });
}

test("Chat provider failure preserves admitted Core work and completed Tools without a hidden continuation", async ({ page, researcher }, testInfo) => {
  test.setTimeout(90_000);
  const requests = observeRuns(page);
  let paused = false;
  try {
    controlWorker("pause"); paused = true;
    await page.goto("/chat");
    await send(page, SCRIPTED_FAILURE_AFTER_ADMISSION_PROMPT);
    await expect(page.locator('.chat-turn-outcome-failed[data-failure-code="PROVIDER_TIMEOUT"]')).toBeVisible({ timeout: 30_000 });
    await expect((await revealToolActivity(page, "submit_research_run", "complete")).last()).toBeVisible();
    const before = databaseFacts(researcher.id);
    expect(before).toMatchObject({ agent_runs: 1, user_messages: 1, active_runs: 0, core_runs: 1 });
    const coreRunId = before.core_run_ids[0]!;
    await page.reload();
    await expect((await revealToolActivity(page, "submit_research_run", "complete")).last()).toBeVisible();
    await expect(page.locator('.chat-turn-outcome-failed[data-failure-code="PROVIDER_TIMEOUT"]')).toBeVisible();
    expect(requests).toHaveLength(1);
    controlWorker("unpause"); paused = false;
    await expect.poll(async () => {
      const response = await page.request.get(`/api/research-runs/${coreRunId}`);
      expect(response.status()).toBe(200);
      return (await response.json()).status;
    }, { timeout: 45_000 }).toBe("succeeded");
    expect(requests).toHaveLength(1);
    await send(page, SCRIPTED_RESUME_RESEARCH_PROMPT);
    await expect(page.getByRole("region", { name: "Factor Evaluation result", exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();
    const after = databaseFacts(researcher.id);
    expect(after).toMatchObject({ agent_runs: 2, user_messages: 2, active_runs: 0, core_runs: 1 });
    await testInfo.attach("independent-core-metadata", { contentType: "application/json", body: Buffer.from(JSON.stringify({ before, after, core_run_id: coreRunId, requests, seed: 0, exit_code: 0 })) });
    await testInfo.attach("recovered-research", { contentType: "image/png", body: await page.screenshot() });
  } finally { if (paused) controlWorker("unpause"); }
});

test("Chat missing login fails before token exchange or durable acceptance", async ({ page, researcher }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/chat");
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeEnabled();
  const before = proxyState("auth-exchange-proxy", 8250).exchange_requests;
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Do not admit this unauthenticated turn.");
  await page.context().clearCookies();
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator(".chat-run-error")).toContainText("rejected before the Turn was accepted");
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("Do not admit this unauthenticated turn.");
  expect(proxyState("auth-exchange-proxy", 8250).exchange_requests).toBe(before);
  expect(databaseFacts(researcher.id)).toMatchObject({ agent_runs: 0, user_messages: 0 });
  await expect(page.locator(".chat-message-user")).toHaveCount(0);
});

async function send(page: Page, prompt: string) {
  await submitChatPrompt(page, prompt);
}
function status(page: Page) { return page.locator("[data-chat-status]"); }
function observeRuns(page: Page) {
  const requests: Array<{ run_id: string; message_id: string; model_key: string; reasoning: string }> = [];
  page.on("request", (request) => {
    if (request.method() !== "POST" || !new URL(request.url()).pathname.endsWith("/agent/research/run")) return;
    const input = request.postDataJSON();
    requests.push({ run_id: input.runId, message_id: input.messages.at(-1).id, model_key: input.forwardedProps.thesistrace.modelKey, reasoning: input.forwardedProps.thesistrace.reasoningEffort });
  });
  return requests;
}

function databaseFacts(researcherId: string): { agent_runs: number; user_messages: number; active_runs: number; core_runs: number; core_run_ids: string[]; models: Array<Record<string, unknown>> } {
  if (!/^[0-9a-f-]{36}$/.test(researcherId)) throw new Error("A validated Researcher identity is required");
  return JSON.parse(execFileSync("docker", ["exec", "--env", "PGPASSWORD=owner-test-password", `${testProjectName()}-postgres-1`,
    "psql", "--username", "thesistrace_owner", "--dbname", "thesistrace", "--tuples-only", "--no-align", "--set", "ON_ERROR_STOP=1", "--command", `
      WITH runs AS (SELECT run.* FROM agent.agent_run run JOIN agent.chat_session session ON run.thread_id = session.id WHERE session.researcher_id = '${researcherId}'::uuid)
      SELECT json_build_object('agent_runs', (SELECT count(*) FROM runs), 'active_runs', (SELECT count(*) FROM runs WHERE status = 'running'),
        'user_messages', (SELECT count(*) FROM agent.mastra_messages message JOIN agent.chat_session session ON message.thread_id = session.id::text WHERE message.role = 'user' AND session.researcher_id = '${researcherId}'::uuid),
        'core_runs', (SELECT count(*) FROM research_runs.runs WHERE researcher_id = '${researcherId}'::uuid),
        'core_run_ids', (SELECT coalesce(json_agg(id ORDER BY id), '[]') FROM research_runs.runs WHERE researcher_id = '${researcherId}'::uuid),
        'models', (SELECT coalesce(json_agg(json_build_object('run_id', id, 'model_key', model_key, 'reasoning', reasoning_effort, 'status', status, 'code', terminal_error_code) ORDER BY started_at), '[]') FROM runs))
    `], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 10_000 }));
}
