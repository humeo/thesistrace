import type { Locator, Page } from "@playwright/test";

type ToolStatus = "complete" | "failed" | "running" | "stopped";

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

function safeToolName(name: string): string {
  if (!/^[a-z0-9_]+$/u.test(name)) throw new Error("Tool assertions require a canonical tool name");
  return name;
}
