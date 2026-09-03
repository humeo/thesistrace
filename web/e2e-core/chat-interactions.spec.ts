import type { BrowserContext, Page } from "@playwright/test";

import { expect, sameOriginHeaders, test } from "./auth-fixture";
import { proxyState, setProxyMode } from "./fault-proxy";

const toolPrompt = "[scripted-tool-turn] Inspect the available research context.";
const askUserPrompt = "[scripted-ask-user] Ask which objective should lead.";

test("Staged FIFO survives reload, Steer stays in the active Turn, and two tabs deliver one follow-up", async ({ page }) => {
  test.setTimeout(90_000);
  const runs = observeRunRequests(page.context());
  let secondPage: Page | undefined;
  setProxyMode("mcp-fault-proxy", 8150, "tool-call", "hold");
  try {
    await page.goto("/chat");
    await send(page, toolPrompt);
    await expect.poll(
      () => proxyState("mcp-fault-proxy", 8150).pending_held_tool_responses,
      { timeout: 30_000 },
    ).toBe(1);
    await expect(status(page)).toHaveText("Research Agent is working");
    await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeEnabled();

    await stage(page, "Keep quality as the primary objective.");
    await stage(page, "Explain the next concrete research step.");
    await expect(page.locator(".chat-staged-queue li")).toHaveCount(2);
    const sessionUrl = page.url();
    expect(new URL(sessionUrl).searchParams.get("session")).toMatch(/^[a-f0-9-]{36}$/u);

    await page.reload();
    await expect(page.locator(".chat-staged-queue li")).toHaveCount(2);
    await expect(status(page)).toHaveText("Research Agent is working");
    secondPage = await page.context().newPage();
    await secondPage.goto(sessionUrl);
    await expect(secondPage.locator(".chat-staged-queue li")).toHaveCount(2);

    await page.getByRole("button", { name: "Steer", exact: true }).click();
    await expect(page.locator(".chat-staged-queue li")).toHaveCount(1);
    await expect(secondPage.locator(".chat-staged-queue li")).toHaveCount(1);
    expect(runs).toHaveLength(1);

    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await expect.poll(() => runs.length, { timeout: 30_000 }).toBe(2);
    await expect(page.locator(".chat-staged-queue")).toHaveCount(0);
    await expect(secondPage.locator(".chat-staged-queue")).toHaveCount(0);
    await expect.poll(async () => latestOutcome(page), { timeout: 30_000 }).toBe("completed");

    expect(runs.map((run) => run.command)).toEqual(["prompt", "prompt"]);
    expect(runs[0]?.messages).toHaveLength(1);
    expect(runs[1]?.messages).toMatchObject([{
      content: "Explain the next concrete research step.",
      role: "user",
    }]);
    const sessionId = new URL(sessionUrl).searchParams.get("session")!;
    const timeline = await timelineEntries(page, sessionId);
    const userInputs = timeline.filter((entry) => entry.kind === "user_input");
    expect(userInputs).toMatchObject([
      { payload: { content: toolPrompt, source: "prompt" }, turn_id: runs[0]?.runId },
      { payload: { content: "Keep quality as the primary objective.", source: "steer" }, turn_id: runs[0]?.runId },
      { payload: { content: "Explain the next concrete research step.", source: "prompt" }, turn_id: runs[1]?.runId },
    ]);
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await secondPage?.close();
  }
});

test("waiting_for_user survives reload and Answer resumes the same Turn", async ({ page }) => {
  const runs = observeRunRequests(page.context());
  await page.goto("/chat");
  await send(page, askUserPrompt);
  await expect(status(page)).toHaveText("Waiting for your answer", { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Which objective should lead?" })).toBeVisible();
  const sessionUrl = page.url();
  const firstRunId = runs[0]?.runId;

  await page.reload();
  await expect(status(page)).toHaveText("Waiting for your answer");
  await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeEnabled();
  await page.getByLabel("Quality").check();
  await page.getByRole("button", { name: "Send answer", exact: true }).click();
  await expect(page.getByText("I will lead with quality and keep risk as a constraint.", { exact: true }))
    .toBeVisible({ timeout: 30_000 });
  await expect.poll(async () => latestOutcome(page)).toBe("completed");

  expect(runs).toHaveLength(2);
  expect(runs[1]).toMatchObject({ command: "answer", messages: [], runId: firstRunId });
  expect(runs[1]?.resume).toMatchObject([{ payload: "Quality", status: "resolved" }]);
  const sessionId = new URL(sessionUrl).searchParams.get("session")!;
  const response = await page.request.get(`/api/agent/sessions/${sessionId}`, { headers: sameOriginHeaders() });
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({
    current_turn: null,
    latest_turn: { id: firstRunId, status: "completed" },
  });
  const question = (await timelineEntries(page, sessionId)).find((entry) => entry.kind === "question");
  expect(question).toMatchObject({ payload: { status: "answered" }, turn_id: firstRunId });
});

test("Stop preserves a partial Turn and Continue starts a new zero-message Turn", async ({ page }) => {
  test.setTimeout(60_000);
  const runs = observeRunRequests(page.context());
  setProxyMode("mcp-fault-proxy", 8150, "tool-call", "hold");
  try {
    await page.goto("/chat");
    await send(page, toolPrompt);
    await expect.poll(
      () => proxyState("mcp-fault-proxy", 8150).pending_held_tool_responses,
      { timeout: 30_000 },
    ).toBe(1);
    await expect(status(page)).toHaveText("Research Agent is working");
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await expect(page.locator('[data-turn-outcome="stopped"]')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();

    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect.poll(() => runs.length, { timeout: 15_000 }).toBe(2);
    await expect.poll(async () => latestOutcome(page), { timeout: 30_000 }).toBe("completed");
    expect(runs[1]).toMatchObject({ command: "continue", messages: [] });
    expect(runs[1]?.runId).not.toBe(runs[0]?.runId);
    await expect(page.locator('[data-turn-outcome="stopped"]')).toHaveCount(1);
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
  }
});

test("Staged storage enforces its limit, preserves order, supports edit/delete, and fails closed on corruption", async ({ page }) => {
  test.setTimeout(120_000);
  setProxyMode("mcp-fault-proxy", 8150, "tool-call", "hold");
  try {
    await page.goto("/chat");
    await send(page, toolPrompt);
    await expect.poll(
      () => proxyState("mcp-fault-proxy", 8150).pending_held_tool_responses,
      { timeout: 30_000 },
    ).toBe(1);

    for (let index = 1; index <= 20; index += 1) {
      await stage(page, `Queued input ${index.toString().padStart(2, "0")}`);
    }
    const rows = page.locator(".chat-staged-queue li");
    await expect(rows).toHaveCount(20);
    await expect(rows.first().locator(".chat-staged-preview")).toHaveText("Queued input 01");
    await expect(rows.last().locator(".chat-staged-preview")).toHaveText("Queued input 20");

    const textarea = page.getByRole("textbox", { name: "Message", exact: true });
    await textarea.fill("This input must remain in the draft");
    await page.getByRole("button", { name: "Stage", exact: true }).click();
    await expect(page.locator(".chat-run-error")).toContainText("This Chat already has 20 staged inputs.");
    await expect(textarea).toHaveValue("This input must remain in the draft");

    await textarea.fill("");
    await rows.nth(1).getByRole("button", { name: "Edit staged input" }).click();
    await expect(textarea).toHaveValue("Queued input 02");
    await expect(rows).toHaveCount(19);
    await textarea.fill("");
    await rows.last().getByRole("button", { name: "Delete staged input" }).click();
    await expect(rows).toHaveCount(18);

    await corruptFirstStagedInput(page);
    await page.reload();
    await expect(page.locator(".chat-run-error")).toContainText("Staged inputs could not be read.");
    await textarea.fill("Do not mutate damaged storage");
    await expect(page.getByRole("button", { name: "Stage", exact: true })).toBeDisabled();
    await page.reload();
    await expect(page.locator(".chat-run-error")).toContainText("Staged inputs could not be read.");
  } finally {
    setProxyMode("mcp-fault-proxy", 8150, "tool-call", "pass");
  }
});

function status(page: Page) {
  return page.locator("[data-chat-status]");
}

async function send(page: Page, content: string): Promise<void> {
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(content);
  await page.getByRole("button", { name: "Send", exact: true }).click();
}

async function stage(page: Page, content: string): Promise<void> {
  const rows = page.locator(".chat-staged-queue li");
  const previousCount = await rows.count();
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(content);
  await page.getByRole("button", { name: "Stage", exact: true }).click();
  await expect(rows).toHaveCount(previousCount + 1);
}

async function latestOutcome(page: Page): Promise<string | null> {
  const outcome = page.locator("[data-turn-outcome]").last();
  return await outcome.count() === 0 ? null : await outcome.getAttribute("data-turn-outcome");
}

async function timelineEntries(page: Page, sessionId: string): Promise<TimelineEntry[]> {
  const response = await page.request.get(
    `/api/agent/sessions/${sessionId}/timeline?limit=50`,
    { headers: sameOriginHeaders() },
  );
  expect(response.status()).toBe(200);
  return (await response.json() as { entries: TimelineEntry[] }).entries;
}

function observeRunRequests(context: BrowserContext): RunRequest[] {
  const requests: RunRequest[] = [];
  context.on("request", (request) => {
    if (request.method() !== "POST" || !new URL(request.url()).pathname.endsWith("/agent/research/run")) return;
    const input = request.postDataJSON() as Record<string, unknown>;
    const forwarded = input.forwardedProps as { thesistrace: { command: string } };
    requests.push({
      command: forwarded.thesistrace.command,
      messages: input.messages as unknown[],
      resume: input.resume as unknown[] | undefined,
      runId: String(input.runId),
    });
  });
  return requests;
}

async function corruptFirstStagedInput(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await new Promise<void>((resolve, reject) => {
      const opening = indexedDB.open("thesistrace-chat-stage", 1);
      opening.onerror = () => reject(opening.error);
      opening.onsuccess = () => {
        const database = opening.result;
        const transaction = database.transaction("items", "readwrite");
        const store = transaction.objectStore("items");
        const reading = store.getAll();
        reading.onerror = () => reject(reading.error);
        reading.onsuccess = () => {
          const first = reading.result[0] as Record<string, unknown> | undefined;
          if (first === undefined) {
            reject(new Error("missing staged fixture"));
            return;
          }
          store.put({ ...first, content: "" });
        };
        transaction.oncomplete = () => { database.close(); resolve(); };
        transaction.onerror = () => reject(transaction.error);
        transaction.onabort = () => reject(transaction.error);
      };
    });
  });
}

type RunRequest = Readonly<{
  command: string;
  messages: readonly unknown[];
  resume?: readonly unknown[];
  runId: string;
}>;

type TimelineEntry = Readonly<{
  kind: string;
  payload: Record<string, unknown>;
  turn_id: string;
}>;
