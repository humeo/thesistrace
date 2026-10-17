import { expect, type Locator, type Page } from "@playwright/test";

type ToolStatus = "complete" | "failed" | "running" | "stopped";
const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

export function toolActivity(page: Page, name: string, status: ToolStatus): Locator {
  const labels = {
    complete: ["Completed", "已完成"], failed: ["Failed", "失败"],
    running: ["Running", "运行中"], stopped: ["Stopped", "已停止"],
  }[status];
  return page.getByRole("listitem", {
    name: new RegExp(`^(?:Tool ${safeToolName(name)}: ${labels[0]}|工具 ${safeToolName(name)}：${labels[1]})$`),
  });
}

export async function revealWorkHistory(page: Page): Promise<void> {
  // Native Think and ThoughtChain unmount collapsed content. Expand the visible
  // history controls before locating their accessible Tool items.
  for (const history of await page.locator(".ant-think").all()) {
    const content = history.locator(".ant-think-content");
    if (!await content.isVisible()) await history.locator(".ant-think-status-wrapper").click();
    await expect(content).toBeVisible();
    for (const group of await content.locator(".ant-thought-chain-node").all()) {
      const trigger = group.locator(":scope > .ant-thought-chain-node-box > .ant-thought-chain-node-header > .ant-thought-chain-node-collapsible");
      if (await trigger.count() === 0) continue;
      const details = group.locator(":scope > .ant-thought-chain-node-box > .ant-thought-chain-node-content");
      if (!await details.isVisible()) await trigger.click();
      await expect(details).toBeVisible();
    }
  }
}

export async function revealToolActivity(
  page: Page,
  name: string,
  status: ToolStatus,
): Promise<Locator> {
  await revealWorkHistory(page);
  const activity = toolActivity(page, name, status);
  await expect(activity.first()).toBeVisible();
  return activity;
}

async function openModelPicker(page: Page): Promise<Locator> {
  const picker = page.getByRole("dialog", { name: "Model and reasoning for the next Turn" });
  if (await picker.count() === 0) {
    await page.getByRole("button", { name: /^Model .* reasoning / }).click();
  }
  return picker;
}

export async function selectModel(page: Page, displayName: string): Promise<void> {
  const picker = await openModelPicker(page);
  const model = picker.getByRole("radio", { name: displayName, exact: true });
  await model.check();
  await expect(model).toBeChecked();
}

export async function selectReasoning(page: Page, label: string): Promise<void> {
  const picker = await openModelPicker(page);
  await picker.getByRole("group", { name: "Reasoning", exact: true })
    .getByRole("button", { name: label, exact: true })
    .click();
}

export function modelPickerTrigger(page: Page): Locator {
  return page.getByRole("button", { name: /^Model .* reasoning / });
}

export function currentChatTitle(page: Page): Locator {
  return page.locator('.chat-session-row > a[aria-current="page"] > span');
}

export async function submitChatPrompt(
  page: Page,
  prompt: string,
  timeoutMs = 30_000,
): Promise<string> {
  const previousTurnId = await latestAuthoritativeTurnId(page);
  await page.getByRole("textbox", { name: "Message", exact: true }).fill(prompt);
  await page.getByRole("button", { name: "Send", exact: true }).click();

  let acceptedTurnId: string | null = null;
  await expect.poll(async () => {
    const turnId = await latestAuthoritativeTurnId(page);
    acceptedTurnId = turnId !== null && turnId !== previousTurnId ? turnId : null;
    return acceptedTurnId ?? "";
  }, {
    message: "a new authoritative Chat Turn to be accepted",
    timeout: timeoutMs,
  }).toMatch(CANONICAL_UUID);

  if (acceptedTurnId === null) throw new Error("CHAT_TURN_ACCEPTANCE_MISSING");
  return acceptedTurnId;
}

async function latestAuthoritativeTurnId(page: Page): Promise<string | null> {
  const sessionId = new URL(page.url()).searchParams.get("session");
  if (sessionId === null) return null;
  if (!CANONICAL_UUID.test(sessionId)) throw new Error("CHAT_SESSION_ID_INVALID");
  const response = await page.request.get(`/api/agent/sessions/${sessionId}`, {
    headers: { origin: new URL(page.url()).origin },
  });
  if (response.status() === 404) return null;
  if (!response.ok()) throw new Error(`CHAT_SESSION_READ_FAILED_${response.status()}`);
  const value = await response.json() as unknown;
  if (!isRecord(value) || !("latest_turn" in value)) {
    throw new Error("CHAT_SESSION_RESPONSE_INVALID");
  }
  if (value.latest_turn === null) return null;
  if (
    !isRecord(value.latest_turn)
    || typeof value.latest_turn.id !== "string"
    || !CANONICAL_UUID.test(value.latest_turn.id)
  ) {
    throw new Error("CHAT_SESSION_TURN_INVALID");
  }
  return value.latest_turn.id;
}

export async function waitForChatTurn(
  page: Page,
  turnId: string,
  expectedStatus: "completed" | "failed" | "stopped" | "waiting_for_user" = "completed",
  timeoutMs = 30_000,
): Promise<void> {
  if (!CANONICAL_UUID.test(turnId)) throw new Error("CHAT_TURN_ID_INVALID");
  const started = Date.now();
  let lastStatus = "not_observed";
  let phase = "model";
  try {
    await expect.poll(async () => {
      const sessionId = new URL(page.url()).searchParams.get("session");
      if (!sessionId || !CANONICAL_UUID.test(sessionId)) return "not_observed";
      const response = await page.request.get(`/api/agent/sessions/${sessionId}`, {
        headers: { origin: new URL(page.url()).origin },
        timeout: Math.max(1, timeoutMs - (Date.now() - started)),
      });
      if (!response.ok()) {
        lastStatus = `http_${response.status()}`;
        throw new Error(`CHAT_SESSION_READ_FAILED_${response.status()}`);
      }
      const value = await response.json();
      const turn = value.current_turn?.id === turnId ? value.current_turn : value.latest_turn;
      lastStatus = turn?.id === turnId ? turn.status : "not_observed";
      return lastStatus;
    }, { timeout: timeoutMs, message: `Turn ${turnId} reaches ${expectedStatus}` }).toBe(expectedStatus);
    if (expectedStatus !== "waiting_for_user") {
      phase = "presentation";
      // Native Bubble.List can complete with an A2UI view and no text footer.
      // Wait for the client to project the same authoritative Turn outcome.
      const outcome = { completed: "Run complete", failed: "Run failed", stopped: "Turn stopped" }[expectedStatus];
      await expect(page.locator(`main[data-agent-run-id="${turnId}"] [data-chat-status]`))
        .toHaveText(outcome, { timeout: 5000 });
    }
  } catch {
    throw new Error(`CHAT_TURN_WAIT_FAILED turn=${turnId} expected=${expectedStatus} last=${lastStatus} phase=${phase} elapsed_ms=${Date.now() - started}`);
  }
}

function safeToolName(name: string): string {
  if (!/^[a-z0-9_]+$/u.test(name)) throw new Error("Tool assertions require a canonical tool name");
  return name;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
