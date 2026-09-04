import { expect, type Locator, type Page } from "@playwright/test";

type ToolStatus = "complete" | "failed" | "running" | "stopped";
const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

export function toolActivity(page: Page, name: string, status: ToolStatus): Locator {
  return page.locator(
    `.chat-tool-group [data-tool-name="${safeToolName(name)}"][data-tool-status="${status}"]`,
  );
}

export async function revealToolActivity(
  page: Page,
  name: string,
  status: ToolStatus,
): Promise<Locator> {
  const activity = toolActivity(page, name, status);
  await activity.first().waitFor({ state: "attached" });
  const groups = activity.locator("xpath=ancestor::details[contains(@class, 'chat-tool-group')]");
  for (const group of await groups.all()) {
    if (await group.getAttribute("open") === null) {
      await group.locator(":scope > summary").click();
    }
  }
  return activity;
}

export async function revealAllToolActivity(page: Page): Promise<void> {
  const closed = page.locator("details.chat-tool-group:not([open]) > summary");
  for (const summary of await closed.all()) await summary.click();
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
  await picker.getByRole("group", { name: "Model", exact: true })
    .getByRole("button", { name: displayName, exact: true })
    .click();
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

function safeToolName(name: string): string {
  if (!/^[a-z0-9_]+$/u.test(name)) throw new Error("Tool assertions require a canonical tool name");
  return name;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
