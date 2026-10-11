import { expect, test } from "@playwright/test";
import { buildModuleProductFixture } from "./build-product-fixture";

declare global { interface Window { queueCompletionProbe: { prompts: { runId: string; inputId: string; content: string }[]; metadataReads: number } } }
let files: Awaited<ReturnType<typeof buildModuleProductFixture>>;
test.use({ viewport: { width: 1200, height: 900 } });
test.beforeAll(async () => { files = await buildModuleProductFixture(new URL("./fixtures/chat-queue.tsx", import.meta.url)); });
test.beforeEach(async ({ context }) => {
  await context.route("https://queue.fixture/**", route => {
    const asset = files.get(new URL(route.request().url()).pathname.slice(1) || "index.html");
    return route.fulfill(asset ?? { status: 404 });
  });
});

test("completion drains FIFO while hidden even when queued runs finish before IndexedDB cleanup", async ({ page }, info) => {
  await page.goto("https://queue.fixture/?fast&hold-accepted");
  await page.getByRole("textbox", { name: "Message" }).fill("First prompt");
  await page.getByRole("button", { name: "send", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("active");
  for (const content of ["Second prompt", "Third prompt"]) {
    await page.getByRole("textbox", { name: "Message" }).fill(content);
    await page.getByRole("button", { name: "stage", exact: true }).click();
    await expect(page.getByRole("list", { name: "Queue" })).toContainText(content);
  }
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.getByRole("button", { name: "Complete current run" }).click();
  await expect.poll(() => page.evaluate(() => window.queueCompletionProbe.prompts.length)).toBe(2);
  await expect(page.getByLabel("Latest turn")).toHaveText("completed");
  await page.getByRole("button", { name: "Finish accepted-input cleanup" }).click();
  await expect.poll(() => page.evaluate(() => window.queueCompletionProbe.prompts.map(item => item.content)), { timeout: 3_000 })
    .toEqual(["First prompt", "Second prompt", "Third prompt"]);
  await expect(page.getByRole("list", { name: "Queue" }).getByRole("listitem")).toHaveCount(0);
  await expect(page.getByRole("status")).toHaveText("idle");
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(await page.evaluate(() => window.queueCompletionProbe.metadataReads)).toBe(1);
  await info.attach("completion-delivery", { body: JSON.stringify(await page.evaluate(() => window.queueCompletionProbe)), contentType: "application/json" });
});

test("two tabs observing completion send the same queued input only once", async ({ page, context }, info) => {
  await page.goto("https://queue.fixture/");
  await page.getByRole("textbox", { name: "Message" }).fill("First prompt");
  await page.getByRole("button", { name: "send", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("active");
  await page.getByRole("textbox", { name: "Message" }).fill("One queued prompt");
  await page.getByRole("button", { name: "stage", exact: true }).click();
  await expect(page.getByRole("list", { name: "Queue" })).toContainText("One queued prompt");
  const runId = await page.evaluate(() => window.queueCompletionProbe.prompts[0]!.runId);
  const other = await context.newPage();
  await other.goto(`https://queue.fixture/?observe=${runId}`);
  await expect(other.getByRole("list", { name: "Queue" })).toContainText("One queued prompt");
  await page.getByRole("button", { name: "Complete current run" }).click();
  await expect.poll(() => page.evaluate(() => window.queueCompletionProbe.prompts.length)).toBe(2);
  await other.getByRole("button", { name: "Complete current run" }).click();
  await page.getByRole("button", { name: "Complete current run" }).click();
  await expect(page.getByRole("list", { name: "Queue" }).getByRole("listitem")).toHaveCount(0);
  await expect(other.getByRole("list", { name: "Queue" }).getByRole("listitem")).toHaveCount(0);
  const sent = [...await page.evaluate(() => window.queueCompletionProbe.prompts), ...await other.evaluate(() => window.queueCompletionProbe.prompts)];
  expect(sent.map(item => item.content)).toEqual(["First prompt", "One queued prompt"]);
  expect(new Set(sent.map(item => item.inputId)).size).toBe(2);
  await info.attach("two-tab-delivery", { body: JSON.stringify(sent), contentType: "application/json" });
});
