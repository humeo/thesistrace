import { expect, test } from "@playwright/test";
import { buildModuleProductFixture } from "./build-product-fixture";

let files: Awaited<ReturnType<typeof buildModuleProductFixture>>;
test.use({ viewport: { width: 1159, height: 780 } });
test.beforeAll(async () => { test.setTimeout(60_000); files = await buildModuleProductFixture(new URL("./fixtures/context-window.tsx", import.meta.url)); });
test.beforeEach(async ({ page }) => {
  await page.route("https://context.fixture/**", route => {
    const path = new URL(route.request().url()).pathname.slice(1) || "index.html";
    const asset = files.get(path);
    return asset ? route.fulfill(asset) : route.fulfill({ status: 404, body: "" });
  });
});

test("native context-window tooltip reads measured usage on hover, focus and reload", async ({ page }) => {
  await page.route("**/api/agent/context-window?**", route => {
    const model = new URL(route.request().url()).searchParams.get("model_key");
    return route.fulfill({ json: { model_key: model, context_window: model === "luna" ? 258_000 : 128_000,
      input_tokens: model === "luna" ? 92_000 : null, measured_at: model === "luna" ? "2026-10-02T08:00:00.000Z" : null } });
  });
  await page.goto("https://context.fixture/");
  const indicator = page.getByRole("button", { name: /Context window.*36% used/ });
  await expect(indicator).toBeVisible();
  await indicator.hover();
  await expect(page.getByRole("tooltip")).toContainText("36% used (64% left)");
  await expect(page.getByRole("tooltip")).toContainText("92k / 258k tokens");
  await expect(page.getByRole("tooltip")).toContainText("Estimated input");
  await page.getByRole("button", { name: "Switch model" }).click();
  const unmeasured = page.getByRole("button", { name: /Context window.*Not measured yet/ });
  await unmeasured.focus();
  await expect(page.getByRole("tooltip")).toContainText("— / 128k tokens");
  await expect(page.getByRole("tooltip")).not.toContainText("36%");
  await page.reload();
  await expect(page.getByRole("button", { name: /Context window.*36% used/ })).toBeVisible();
  await page.getByRole("button", { name: "简体中文", exact: true }).click();
  await page.getByRole("button", { name: /上下文窗口.*已用 36%/ }).focus();
  await expect(page.getByRole("tooltip")).toContainText("剩余 64%");
  await page.getByRole("button", { name: /上下文窗口.*已用 36%/ }).press("Escape");
  await expect(page.getByRole("tooltip")).toBeHidden();
});

test("unavailable context statistics stay unknown", async ({ page }) => {
  await page.route("**/api/agent/context-window?**", route => route.fulfill({ status: 503, json: { code: "AGENT_SERVICE_UNAVAILABLE" } }));
  await page.goto("https://context.fixture/");
  await page.getByRole("button", { name: /Context window.*Statistics unavailable/ }).focus();
  await expect(page.getByRole("tooltip")).toContainText("Statistics unavailable");
  await expect(page.getByRole("tooltip")).not.toContainText("0%");
});
